"""Code-Wire extractor: compare the `# node:` marks in Python code with a Code-Wire graph (.md, format B).

Usage: python codewire_extract.py --repo <path> --graph <graph.md> [--path <folder>] --out <dir>

For each node it compares the mark, the def and the contract: the inputs with their types and default
values, the output type and the module. It also lists the real calls between marked nodes, lifted through
unmarked helpers, so a reader sees who calls whom. `--path` keeps only the marks in the files of one slice.
Writes <out>/extract.json and <out>/diff-report.md. Stdlib only.
`parse_text` gives the parse of one graph text (Notation-Grammar.md), and `unread` gives the lines that
the parser does not read. `codewire_lint.py` prints them.
"""
import argparse
import ast
import json
import re
from pathlib import Path

MARK_RE = re.compile(r"^\s*#\s*node:\s*(\S+)\s*(?:\[([^\]]*)\])?")
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".dev-flow"}
NODE_KEYS = ("req", "in", "out", "func", "module", "modify", "volatile", "oracle")  # and `examples:`
REPEAT_KEYS = ("examples", "oracle")   # a key that can have more than one line in a node
ENTITY_KEYS = ("in", "desc", "sequence", "offers")
OFFER = re.compile(r'^offers:\s*(\([^)]*\)\s*)?"([^"]+)"\s*→\s*(\S+)\s*$')
FINDING_KEYS = ("anchor", "seen", "cause", "effect", "decision")
SECTIONS = ("Nodes", "Entities", "Edges", "Findings")
ENTITY_END = re.compile(r"^(\[[^\]]*\])(.*)$")   # an entity, then maybe `.field` (A3d)
FIELD = re.compile(r"^\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)$")
ASSIGN_RE = re.compile(r"\s*\((replace|clear|append)\)\s*$")
TYPING_ALIASES = {"List": "list", "Dict": "dict", "Tuple": "tuple", "Set": "set", "FrozenSet": "frozenset", "Type": "type"}
ARROW = "──▶"
MAX_LIFT_DEPTH = 6


# ---------- code side ----------

def iter_py_files(repo):
    for p in sorted(repo.rglob("*.py")):
        if not SKIP_DIRS.intersection(p.relative_to(repo).parts):
            yield p


def parse_files(repo):
    """Return {relpath: (source_lines, ast_tree)} and a list of files that failed to parse."""
    parsed, failed = {}, []
    for p in iter_py_files(repo):
        rel = p.relative_to(repo).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
            parsed[rel] = (text.splitlines(), ast.parse(text))
        except (SyntaxError, UnicodeDecodeError) as exc:
            failed.append({"file": rel, "error": str(exc)})
    return parsed, failed


def defs_with_qualnames(tree):
    """Yield (qualname, FunctionDef, enclosing class name or None) for every function/method."""
    def walk(node, prefix, cls):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from walk(child, prefix + child.name + ".", child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield prefix + child.name, child, cls
                yield from walk(child, prefix + child.name + ".<locals>.", None)
    yield from walk(tree, "", None)


def signature(fn):
    a = fn.args
    positional = a.posonlyargs + a.args
    pos_defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    params = []
    for arg, default in list(zip(positional, pos_defaults)) + list(zip(a.kwonlyargs, a.kw_defaults)):
        params.append({"name": arg.arg, "type": ast.unparse(arg.annotation) if arg.annotation else None,
                       "default": ast.unparse(default) if default is not None else None})
    for star, arg in (("*", a.vararg), ("**", a.kwarg)):
        if arg:
            params.append({"name": star + arg.arg, "type": ast.unparse(arg.annotation) if arg.annotation else None,
                           "default": None})
    if params and params[0]["name"] in ("self", "cls"):
        params = params[1:]
    returns = ast.unparse(fn.returns) if fn.returns else None
    return params, returns


def extract_marks(parsed):
    marks = []
    for rel, (lines, tree) in parsed.items():
        start_of = {}
        for qual, fn, _ in defs_with_qualnames(tree):
            first = min([fn.lineno] + [d.lineno for d in fn.decorator_list])
            start_of[first] = (qual, fn)
        for i, line in enumerate(lines, start=1):
            m = MARK_RE.match(line)
            if not m:
                continue
            reqs = None if m.group(2) is None else [r.strip() for r in m.group(2).split(",") if r.strip()]
            nxt = next((j for j in range(i + 1, len(lines) + 1) if lines[j - 1].strip()), None)
            mark = {"name": m.group(1), "reqs": reqs, "file": rel, "line": i, "def": None}
            if nxt in start_of:
                qual, fn = start_of[nxt]
                params, returns = signature(fn)
                mark["def"] = {"qualname": qual, "line": fn.lineno, "params": params, "returns": returns}
            marks.append(mark)
    return marks


# ---------- graph side (format B) ----------

def split_top(text, sep):
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch in "[({":
            depth += 1
        elif ch in "])}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def graph_type(t):
    """Graph type notation to Python-ish: trailing `?` -> Optional[...]; `A->B` -> Callable[[A], B];
    `(A->B)?` -> Optional[Callable[[A], B]] (optional function, Q28)."""
    t = t.strip()
    if t.startswith("(") and t.endswith(")?"):
        return f"Optional[{graph_type(t[1:-2])}]"
    if t.startswith("(") and t.endswith(")"):
        return graph_type(t[1:-1])
    if "->" in t:
        arg, ret = (graph_type(x) for x in t.split("->", 1))
        return f"Callable[[{arg}], {ret}]"
    return nested_optional(t)


def nested_optional(t):
    """`X?` -> `Optional[X]` at any depth: `Sequence[int?]?` -> `Optional[Sequence[Optional[int]]]`."""
    while "?" in t:
        q = t.index("?")
        start = q
        if start and t[start - 1] == "]":
            depth = 0
            while True:
                start -= 1
                depth += {"]": 1, "[": -1}.get(t[start], 0)
                if depth == 0:
                    break
        while start and (t[start - 1].isalnum() or t[start - 1] in "_."):
            start -= 1
        t = f"{t[:start]}Optional[{t[start:q].strip()}]{t[q + 1:]}"
    return t


def parse_decl(item):
    """`type name [= default]`, `(Callable) A->B name`, `Class self` -> {kind, type, name, default}."""
    item = item.strip()
    default = None
    if " = " in item:
        item, default = (x.strip() for x in item.split(" = ", 1))
    kind = "value"
    if item.startswith("(Callable)"):
        kind, item = "callable", item[len("(Callable)"):].strip()
    if " " not in item:
        return {"kind": "untyped", "type": None, "name": item, "default": default}
    typ, name = item.rsplit(" ", 1)
    if name == "self":
        kind = "self"
    return {"kind": kind, "type": graph_type(typ), "name": name, "default": default}


def parse_out(text):
    text = re.sub(r"\{[^}]*\}", "", text).strip()
    if text == "None":  # the node only modifies (§3.1 `out:`): no value, no name
        return {"type": "None", "names": [], "raw": text}
    if text.startswith("tuple(") and text.endswith(")"):
        comps = [parse_decl(c) for c in split_top(text[len("tuple("):-1], ",")]
        return {"type": "tuple[" + ", ".join(c["type"] or "?" for c in comps) + "]",
                "names": [c["name"] for c in comps], "raw": text}
    d = parse_decl(text)
    return {"type": d["type"], "names": [d["name"]], "raw": text}


def section(md_text, title):
    """Body of `## title` up to the next level-2 heading (level-3 subsections included)."""
    m = re.search(rf"^## {re.escape(title)}\s*$(.*?)(?=^## |\Z)", md_text, re.S | re.M)
    return m.group(1) if m else ""


def parse_graph(md_text):
    nodes = []
    for block in re.split(r"\n\s*\n", section(md_text, "Nodes")):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if len(lines) < 2 or lines[0].startswith(("[", "#", ">")) or ":" in lines[0]:
            continue
        fields, examples, oracle = {}, [], []
        for line in lines[1:]:
            m = re.match(r"(\w+):\s*(.*)$", line)
            if m and m.group(1) == "examples":  # repeatable: one line per input → output pair
                examples.append(m.group(2).strip())
            elif m and m.group(1) == "oracle":  # repeatable: one line per outside source
                oracle.append(m.group(2).strip())
            elif m and m.group(1) in NODE_KEYS:
                fields.setdefault(m.group(1), m.group(2).strip())  # a second line of a key is G3: skipped
        if "in" not in fields and "out" not in fields:
            continue
        req = fields.get("req")
        reqs = None if req is None else [] if req == "to trace" else [r.strip() for r in req.split(",") if r.strip()]
        modify = split_top(fields.get("modify", ""), ";")
        nodes.append({
            "name": lines[0].strip(),
            "reqs": reqs,
            "in": [parse_decl(i) for i in split_top(fields.get("in", ""), ";")],
            "out": parse_out(fields.get("out", "")),
            "module": fields.get("module") or None,
            "examples": examples,
            # `modify:` targets without their assignment kind: an entity `[...]` or an input path (Q28)
            "modify": [ASSIGN_RE.sub("", x).strip() for x in modify],
            "assign": [ASSIGN_RE.search(x).group(1) if ASSIGN_RE.search(x) else None for x in modify],
            "func": fields.get("func") or None,
            "volatile": [x.strip() for x in fields.get("volatile", "").split(",") if x.strip()],
            "oracle": oracle,
        })
    return nodes


def parse_entities(md_text):
    """Names of the `[Kind: name]` blocks declared in `## Entities`."""
    return [l.strip() for l in section(md_text, "Entities").splitlines() if l.strip().startswith("[")]


def load_graphs(texts):
    """Merge several graph files that share one repo: nodes by name (the first wins; the same name with
    another contract or another `req:` is a conflict), edges and entities concatenated."""
    nodes, edges, entities, conflicts = {}, [], [], []
    for md in texts:
        for n in parse_graph(md):
            if n["name"] in nodes:
                a = nodes[n["name"]]
                if (a["in"], a["out"]["type"], a["module"], a["reqs"]) != (n["in"], n["out"]["type"], n["module"], n["reqs"]):
                    conflicts.append(n["name"])
                else:  # the same node in two flows: each brings its own thread
                    a["examples"] += [e for e in n["examples"] if e not in a["examples"]]
            else:
                nodes[n["name"]] = n
        entities += parse_entities(md)
    names = list(nodes)
    for md in texts:
        edges += parse_edges(md, names)
    return list(nodes.values()), edges, list(dict.fromkeys(entities)), conflicts


def parse_edges(md_text, node_names):
    """Every `A ──▶ B` line of `## Edges`; a following `when:` line is attached to the edge.
    An endpoint is an entity `[...]` with an optional `.field`, or `<node>[.<port>]`, the node being the
    longest known prefix."""
    def endpoint(text):
        text = text.strip()
        e = ENTITY_END.match(text)
        if e:
            f = FIELD.match(e.group(2).strip())
            return {"entity": e.group(1), "field": f.group(1) if f else e.group(2).strip() or None, "node": None, "port": None}
        for name in sorted(node_names, key=len, reverse=True):
            if text == name or text.startswith(name + "."):
                return {"entity": None, "field": None, "node": name, "port": text[len(name) + 1:] or None}
        return {"entity": None, "field": None, "node": None, "port": None, "unknown": text}

    edges = []
    for line in section(md_text, "Edges").splitlines():
        line = line.strip()
        if ARROW in line:
            src, dst = line.split(ARROW, 1)
            edges.append({"src": endpoint(src), "dst": endpoint(dst), "when": None, "raw": line})
        elif line.startswith("when:") and edges:
            edges[-1]["when"] = line[len("when:"):].strip()
    return edges


# ---------- full parse and the lines that it does not read ----------

def numbered_sections(md_text):
    """{title: [(line number, line)]} for each `## ` section; a second section with the same title is not read."""
    out, cur = {}, None
    for i, line in enumerate(md_text.splitlines(), 1):
        m = re.match(r"## (.*?)\s*$", line)
        if m:
            cur = m.group(1) if m.group(1) not in out else None
            if cur:
                out[cur] = []
        elif cur:
            out[cur].append((i, line))
    return out


def numbered_blocks(lines):
    """The groups of non-blank lines, with no note block (`###` or `>`)."""
    blocks, cur = [], []
    for i, line in lines + [(0, "")]:
        if line.strip():
            cur.append((i, line))
        elif cur:
            if not cur[0][1].lstrip().startswith(("#", ">")):
                blocks.append(cur)
            cur = []
    return blocks


def parse_step(text):
    """A step of a `sequence:` line: `node [wins] [(!)] [(prose)]`."""
    m = re.match(r"(.+?)( wins)?( \(!\))?( \(.*\))?$", text.strip())
    return {"node": m.group(1).strip(), "wins": bool(m.group(2)), "early": bool(m.group(3))}


def entity_kind(name):
    m = re.match(r"\[([^:\]]+):", name)
    return m.group(1).strip() if m else None


def parse_entity_blocks(md_text):
    """The `[Kind: name]` blocks of `## Entities` with their fields: `in:`, `desc:` and the `sequence:` lines."""
    out = []
    for block in numbered_blocks(numbered_sections(md_text).get("Entities", [])):
        name = block[0][1].strip()
        if not name.startswith("["):
            continue
        ent, in_seq = {"name": name, "kind": entity_kind(name), "in": None, "desc": None, "sequence": [], "offers": []}, False
        for _, line in block[1:]:
            ev = re.match(r"\s+(\w+):\s*(.*)$", line)
            if in_seq and ev:
                ent["sequence"].append({"event": ev.group(1), "steps": [parse_step(s) for s in ev.group(2).split("→")]})
                continue
            o = OFFER.match(line.strip())
            if o:
                ent["offers"].append({"source": example_source(o.group(1)) if o.group(1) else None,
                                      "control": o.group(2), "node": o.group(3)})
                continue
            f = re.match(r"(\w+):\s*(.*)$", line)
            in_seq = bool(f) and f.group(1) == "sequence"
            if f and f.group(1) in ("in", "desc") and ent[f.group(1)] is None:
                ent[f.group(1)] = f.group(2).strip() or None
        out.append(ent)
    return out


def example_source(line):
    """The source in the parentheses of an `examples:` line: {thread, step, root}.
    `(T1, t1a)`, `(U2, U2.4, root TuiApp.on_button_pressed)`."""
    src = {"thread": None, "step": None, "root": None}
    m = re.match(r"\s*\(([^)]*)\)", line)
    if not m:
        return src
    for i, part in enumerate(p.strip() for p in m.group(1).split(",")):
        word = part.split(" ")[0]
        if word == "root" and len(part.split()) == 2:
            src["root"] = part.split()[1]
        elif i == 0:
            src["thread"] = part
        elif src["step"] is None:
            src["step"] = part
    return src


def parse_findings(md_text):
    """The `finding <id> <title>` blocks of `## Findings` with their fields."""
    out = []
    for block in numbered_blocks(numbered_sections(md_text).get("Findings", [])):
        m = re.match(r"finding\s+(\S+)\s*(.*)$", block[0][1].strip())
        if not m:
            continue
        f = {"id": m.group(1), "title": m.group(2).strip() or None, **{k: None for k in FINDING_KEYS}}
        for _, line in block[1:]:
            fm = re.match(r"(\w+):\s*(.*)$", line)
            if fm and fm.group(1) in FINDING_KEYS and f[fm.group(1)] is None:
                f[fm.group(1)] = fm.group(2).strip() or None
        out.append(f)
    return out


def unread(md_text):
    """The lines that the parser does not read: [{line, text}]. A tool skips such a line with no word,
    so each one is an error. (In the app data audit, two merged blocks lost a node from the recording.)"""
    secs = numbered_sections(md_text)
    out = []

    def miss(i, text):
        out.append({"line": i, "text": text})

    def fields(block, keys, where, repeat=()):
        seen = set()
        for i, line in block[1:]:
            f = re.match(r"(\w+):", line)
            key = f.group(1) if f else None
            if key not in keys:
                miss(i, f"`{line.strip()[:40]}` in {where}: not a field")
            elif key in seen and key not in repeat:
                miss(i, f"`{key}:` a second time in {where}")
            seen.add(key)
        return seen

    for i, line in enumerate(md_text.splitlines(), 1):
        m = re.match(r"## (.*?)\s*$", line)
        if m and m.group(1) not in SECTIONS:
            miss(i, f"section `{m.group(1)}`")
    for block in numbered_blocks(secs.get("Nodes", [])):
        i, first = block[0][0], block[0][1].strip()
        if first.startswith("[") or ":" in first:
            miss(i, f"`{first[:40]}`: a block in `## Nodes` with no name line")
            continue
        if not {"in", "out"} & fields(block, NODE_KEYS + ("examples",), f"node `{first}`", REPEAT_KEYS):
            miss(i, f"node `{first}` has no `in:` and no `out:`")
            continue
        value = lambda key: next((l.split(":", 1)[1].strip() for _, l in block if l.startswith(key + ":")), "")  # noqa: E731
        names = {parse_decl(x)["name"] for x in split_top(value("in"), ";") if x.strip()}
        names |= set(parse_out(value("out"))["names"]) | {"out"}
        for j, line in block[1:]:
            if line.startswith("volatile:"):   # the recorder masks nothing for such an item
                for item in (x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()):
                    if item.split(".")[0] not in names:
                        miss(j, f"volatile `{item}` of `{first}`: not an input, an output or `out`")
    for block in numbered_blocks(secs.get("Entities", [])):
        first = block[0][1].strip()
        if not first.startswith("["):
            miss(block[0][0], f"`{first[:40]}`: a block in `## Entities` with no `[Kind: name]` line")
            continue
        rest = [(i, l) for i, l in block if not re.match(r"\s+\w+:", l)]  # the lines under `sequence:`
        fields(rest, ENTITY_KEYS, f"entity `{first}`", ("offers",))
        for i, line in rest[1:]:
            if line.strip().startswith("offers:") and not OFFER.match(line.strip()):
                miss(i, f"`{line.strip()[:50]}`: not of the form offers: (source) \"control\" → node")
    edge_before = False
    for i, line in secs.get("Edges", []):
        s = line.strip()
        if not s or s.startswith(("#", ">")):
            continue
        if ARROW in s:
            edge_before = True
            for end in s.split(ARROW, 1):
                e = ENTITY_END.match(end.strip())
                if e and e.group(2).strip() and not FIELD.match(e.group(2).strip()):
                    miss(i, f"`{end.strip()}`: after the entity, `{e.group(2).strip()}` is not `.` and a name")
        elif s.startswith("when:"):
            if not edge_before:
                miss(i, "`when:` with no edge before it")
        else:
            miss(i, f"`{s[:40]}`: not an edge")
    for block in numbered_blocks(secs.get("Findings", [])):
        i, first = block[0][0], block[0][1].strip()
        if not re.match(r"finding\s+\S+", first):
            miss(i, f"`{first[:40]}`: a block in `## Findings` with no `finding` line")
            continue
        fields(block, FINDING_KEYS, f"finding `{first.split()[1]}`")
    return sorted(out, key=lambda x: x["line"])


def parse_text(md_text):
    """The full parse of one graph text, in the shape of Notation-Grammar.md: nodes, entities, edges,
    findings, and the lines that the parser does not read."""
    nodes, edges, entities, _ = load_graphs([md_text])
    blocks = {e["name"]: e for e in parse_entity_blocks(md_text)}
    end = lambda p: {k: p[k] for k in ("node", "port", "entity", "field")}  # noqa: E731
    return {
        "nodes": [{"name": n["name"], "reqs": n["reqs"], "in": n["in"], "out": n["out"], "func": n["func"],
                   "module": n["module"], "examples": n["examples"],
                   "modify": [{"target": t, "assign": a} for t, a in zip(n["modify"], n["assign"])],
                   "volatile": n["volatile"], "oracle": n["oracle"]} for n in nodes],
        "entities": [blocks.get(e, {"name": e, "kind": entity_kind(e), "in": None, "desc": None, "sequence": [], "offers": []})
                     for e in entities],
        "edges": [{"src": end(e["src"]), "dst": end(e["dst"]), "when": e["when"], "raw": e["raw"]} for e in edges],
        "findings": parse_findings(md_text),
        "unread": unread(md_text),
    }


# ---------- the real calls: call resolution and lifting ----------

def index_defs(parsed, skip_tests=True):
    """{def_id: info} with def_id = `file::qualname`, plus lookup tables for call resolution."""
    defs, top_funcs, classes = {}, {}, {}
    for rel, (_, tree) in parsed.items():
        if skip_tests and "tests" in rel.split("/"):
            continue
        for qual, fn, cls in defs_with_qualnames(tree):
            did = f"{rel}::{qual}"
            defs[did] = {"file": rel, "qual": qual, "fn": fn, "cls": cls}
            if "." not in qual:
                top_funcs.setdefault(qual, []).append(did)
            elif cls and qual.count(".") == 1:
                classes.setdefault(cls, {})[qual.split(".")[1]] = did
    return defs, top_funcs, classes


def own_calls(fn):
    """Call nodes in a def's body, not descending into nested defs or classes (they are defs of their own)."""
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def own_refs(fn, calls):
    """Names in a def's body that are read as a value, not called: `pool.map(f, xs)`, `g = f`.
    A parameter or a local assignment with the same name hides the function, so it is not a ref."""
    called = {id(c.func) for c in calls}
    local = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
    names, stack = [], list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                local.add(node.id)
            elif id(node) not in called:
                names.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return [n for n in names if n.id not in local]


def local_def(name, info, defs):
    """The nested def `name` that the def of `info` sees: its own, then the ones of each enclosing def."""
    qual = info["qual"]
    while True:
        did = f"{info['file']}::{qual}.<locals>.{name}"
        if did in defs:
            return did
        if ".<locals>." not in qual:
            return None
        qual = qual.rsplit(".<locals>.", 1)[0]


def resolve(call, info, top_funcs, classes, marked_methods, defs=None):
    """Name-based resolution. `f()` -> top-level f (same file first); `C()` -> C.__init__;
    `self.m()` -> m of the enclosing class; `x.m()` -> top-level m or a marked method m."""
    f = call.func
    if isinstance(f, ast.Name):
        nested = local_def(f.id, info, defs or {})
        if nested:
            return [nested]
        if f.id in classes:
            return [classes[f.id]["__init__"]] if "__init__" in classes[f.id] else []
        cands = top_funcs.get(f.id, [])
        same = [d for d in cands if d.startswith(info["file"] + "::")]
        return same or cands
    if isinstance(f, ast.Attribute):
        if isinstance(f.value, ast.Name) and f.value.id in ("self", "cls") and info["cls"]:
            did = classes.get(info["cls"], {}).get(f.attr)
            return [did] if did else []
        if f.attr == "__init__":  # super().__init__() / Base.__init__(self): not a construction
            return []
        return top_funcs.get(f.attr, []) + marked_methods.get(f.attr, [])
    return []


def lift_calls(parsed, marks):
    """O2: for each marked node X, walk its calls; an unmarked callee is traversed as part of X
    (up to MAX_LIFT_DEPTH), a marked callee Y yields the lifted edge X -> Y with its call site.
    Returns (edges {(X, Y): [sites]}, top_level_sites {Y: [sites]}, ambiguous_calls)."""
    defs, top_funcs, classes = index_defs(parsed)
    marked = {f"{m['file']}::{m['def']['qualname']}": m["name"] for m in marks if m["def"]}
    marked_methods = {}
    for did in marked:
        qual = did.split("::", 1)[1]
        if "." in qual:
            marked_methods.setdefault(qual.rsplit(".", 1)[1], []).append(did)

    calls_of, ambiguous = {}, 0
    for did, info in defs.items():
        out, calls = [], list(own_calls(info["fn"]))
        for call in calls:
            targets = list(dict.fromkeys(resolve(call, info, top_funcs, classes, marked_methods, defs)))
            ambiguous += len(targets) > 1
            out += [(t, f"{info['file']}:{call.lineno}") for t in targets]
        for ref in own_refs(info["fn"], calls):  # a function as a value counts as a call, marked `(ref)`
            nested = local_def(ref.id, info, defs)
            targets = [nested] if nested else top_funcs.get(ref.id, [])
            out += [(t, f"{info['file']}:{ref.lineno} (ref)") for t in targets]
        calls_of[did] = out

    edges, reached = {}, set()
    for x_id, x_name in marked.items():
        stack, seen = [(x_id, 0)], {x_id}
        while stack:
            did, depth = stack.pop()
            reached.add(did)
            for target, site in calls_of.get(did, []):
                if target in marked:
                    if target != x_id:
                        edges.setdefault((x_name, marked[target]), []).append(site)
                elif target not in seen and depth < MAX_LIFT_DEPTH:
                    seen.add(target)
                    stack.append((target, depth + 1))

    top_level = {}
    for did, out in calls_of.items():
        if did in reached:
            continue
        for target, site in out:
            if target in marked:
                top_level.setdefault(marked[target], []).append(site)
    return {k: sorted(set(v)) for k, v in edges.items()}, {k: sorted(set(v)) for k, v in top_level.items()}, ambiguous


# ---------- comparison ----------

def norm_type(t):
    """Normalise for comparison: drop spaces/quotes, typing aliases to builtins, `X | None` to Optional[X]."""
    if t is None:
        return None
    t = t.replace(" ", "").replace("'", "").replace('"', "")
    for alias, builtin in TYPING_ALIASES.items():
        t = re.sub(rf"\b{alias}\[", builtin + "[", t)
        t = re.sub(rf"\b{alias}\b", builtin, t)
    if t.endswith("|None"):
        t = f"Optional[{t[:-5]}]"
    return t


def erase_dict_params(t):
    """`dict[str,Any]` -> `dict`, at any depth (bracket-aware)."""
    out, i = "", 0
    while i < len(t):
        if t.startswith("dict[", i):
            depth, j = 0, i + 4
            while True:
                depth += {"[": 1, "]": -1}.get(t[j], 0)
                j += 1
                if depth == 0:
                    break
            out, i = out + "dict", j
        else:
            out, i = out + t[i], i + 1
    return out


def type_match(graph_t, code_t):
    """exact | loose | mismatch. Loose: the graph names only the bare container of a parameterised
    code type at the top level (`dict` vs `dict[str, Any]`), or the types agree once every
    `dict[...]` is erased to `dict` (graph wrote `list[dict]` for `list[dict[str, Any]]`)."""
    g, c = norm_type(graph_t), norm_type(code_t)
    if g == c:
        return "exact"
    if g and c and ("[" not in g and c.split("[")[0] == g or erase_dict_params(g) == erase_dict_params(c)):
        return "loose"
    return "mismatch"


def norm_default(d):
    return None if d is None else d.replace(" ", "").replace("'", '"')


def diff(marks, graph_nodes, lifted, top_level, conflicts=()):
    """The differences between the marks, the defs and the graph contracts, and the list of the real calls."""
    findings = []

    def add(kind, where, msg):
        findings.append({"kind": kind, "where": where, "msg": msg})

    for name in conflicts:
        add("graph_node_conflict", name, f"`{name}` is declared in two graph files with another contract or `req:`")

    by_mark = {}
    for m in marks:
        where = f"{m['file']}:{m['line']}"
        if m["name"] in by_mark:
            add("duplicate_mark", where, f"`{m['name']}` also marked at {by_mark[m['name']]['file']}:{by_mark[m['name']]['line']}")
        by_mark.setdefault(m["name"], m)
        if m["def"] is None:
            add("dangling_mark", where, f"`{m['name']}` is not directly above a def")
        elif m["def"]["qualname"] != m["name"]:
            add("mark_name_ne_qualname", where, f"mark `{m['name']}` vs def `{m['def']['qualname']}`")

    nodes = {n["name"]: n for n in graph_nodes}
    for m in marks:
        if m["name"] not in nodes:
            add("mark_without_graph_node", f"{m['file']}:{m['line']}", f"`{m['name']}`")

    for node in graph_nodes:
        if not node.get("examples"):
            add("graph_examples_missing", node["module"] or "?", f"`{node['name']}` has no `examples:` line")
        m = by_mark.get(node["name"])
        if m is None:
            add("graph_node_without_mark", node["module"] or "?", f"`{node['name']}`")
            continue
        where = f"{m['file']}:{m['line']}"
        d = m["def"]
        if node["module"] and m["file"] != node["module"]:
            add("module_mismatch", where, f"graph says `{node['module']}`")
        if d is None:
            continue
        code_params = {p["name"]: p for p in d["params"]}
        graph_in = {p["name"]: p for p in node["in"] if p["kind"] != "self"}
        for name in graph_in:
            if name not in code_params:
                add("input_missing_in_code", where, f"graph input `{name}` not a parameter of `{d['qualname']}`")
        for name, p in code_params.items():
            if name not in graph_in:
                add("input_missing_in_graph", where, f"parameter `{name}: {p['type']}` not in graph")
        for name, gp in graph_in.items():
            cp = code_params.get(name)
            if cp is None:
                continue
            if gp["type"] is None:
                add("input_untyped_in_graph", where, f"`{name}` has no type in graph (code: `{cp['type']}`)")
            elif cp["type"] is None:
                add("input_untyped_in_code", where, f"`{name}` has no annotation (graph: `{gp['type']}`)")
            else:
                level = type_match(gp["type"], cp["type"])
                if level == "mismatch":
                    add("input_type_mismatch", where, f"`{name}`: graph `{gp['type']}` vs code `{cp['type']}`")
                elif level == "loose":
                    add("info_type_loose", where, f"`{name}`: graph `{gp['type']}` vs code `{cp['type']}`")
            if norm_default(gp["default"]) != norm_default(cp["default"]):
                add("default_mismatch", where, f"`{name}`: graph default `{gp['default']}` vs code `{cp['default']}`")

        g_out, c_out = node["out"]["type"], d["returns"]
        if node["name"].endswith(".__init__"):
            cls = node["name"].rsplit(".", 2)[-2]
            if g_out and norm_type(g_out) != cls:
                add("output_type_mismatch", where, f"constructor node: graph `{g_out}` vs class `{cls}`")
        elif c_out is None:
            add("output_untyped_in_code", where, f"graph `{g_out}`, no return annotation")
        else:
            level = type_match(g_out, c_out)
            if level == "mismatch":
                add("output_type_mismatch", where, f"graph `{g_out}` vs code `{c_out}`")
            elif level == "loose":
                add("info_type_loose", where, f"output: graph `{g_out}` vs code `{c_out}`")

    calls = [{"caller": x, "callee": y, "sites": sites} for (x, y), sites in sorted(lifted.items())]
    return findings, calls


KIND_TITLES = {
    "graph_node_without_mark": "Graph node without mark (no code yet)",
    "mark_without_graph_node": "Mark without graph node",
    "duplicate_mark": "Same node marked twice",
    "dangling_mark": "Mark not bound to a def",
    "mark_name_ne_qualname": "Mark name differs from def qualname",
    "module_mismatch": "Module/file mismatch",
    "graph_examples_missing": "Graph node has no `examples:`",
    "graph_node_conflict": "Same node with another contract or `req:` in two graph files",
    "input_missing_in_code": "Input in graph, not a parameter in code",
    "input_missing_in_graph": "Parameter in code, not an input in graph",
    "input_type_mismatch": "Input type mismatch",
    "input_untyped_in_graph": "Input untyped in graph (cannot compare)",
    "input_untyped_in_code": "Parameter unannotated in code (cannot compare)",
    "default_mismatch": "Default value mismatch",
    "output_type_mismatch": "Output type mismatch",
    "output_untyped_in_code": "Return unannotated in code (cannot compare)",
    "info_type_loose": "Info: graph names the bare container only (loose match)",
}


def render_report(findings, marks, graph_nodes, calls, top_level, ambiguous, failed):
    drift = sum(not f["kind"].startswith("info_") for f in findings)
    out = ["# Code-Wire extractor report", "",
           f"- Marks found: {len(marks)}",
           f"- Graph nodes parsed: {len(graph_nodes)}",
           f"- Real calls between marked nodes: {len(calls)}",
           f"- Findings: {len(findings)} ({drift} drift, {len(findings) - drift} info)",
           f"- Ambiguous call resolutions (a name matched several defs): {ambiguous}",
           f"- Files that failed to parse: {len(failed)}", "",
           "Type normalisation: spaces and quotes dropped; `List/Dict/Tuple/Set` -> builtins; "
           "`X | None` and graph `X?` -> `Optional[X]`; graph `(Callable) A->B` -> `Callable[[A], B]`; graph "
           "`tuple(A a, B b)` -> `tuple[A, B]`. A bare graph container (`dict`) against a parameterised code "
           "type (`dict[str, Any]`) is info (loose match), not drift.", "",
           "Call resolution is name-based (`f()`, `Class()` -> `__init__`, `self.m()`, `x.m()` -> top-level `m` "
           "or a marked method `m`); dynamic calls and callables passed as values are not seen. Tests excluded.", "",
           "## Counts", "", "| Kind | Count |", "|---|---|"]
    kinds = [k for k in KIND_TITLES if any(f["kind"] == k for f in findings)]
    for k in kinds:
        out.append(f"| {KIND_TITLES[k]} | {sum(f['kind'] == k for f in findings)} |")
    out += ["", "## Real calls between marked nodes", "", "| Caller | Callee | Sites |", "|---|---|---|"]
    out += [f"| `{c['caller']}` | `{c['callee']}` | {', '.join(c['sites'])} |" for c in calls]
    if top_level:
        out += ["", "Top-level sites (no marked node above them):", ""]
        out += [f"- `{y}`: {', '.join(s)}" for y, s in sorted(top_level.items())]
    for k in kinds:
        out += ["", f"## {KIND_TITLES[k]}", ""]
        out += [f"- `{f['where']}` — {f['msg']}" for f in findings if f["kind"] == k]
    if failed:
        out += ["", "## Files skipped (parse error)", ""] + [f"- `{f['file']}`: {f['error']}" for f in failed]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--graph", required=True, type=Path, action="append",
                    help="graph file; repeat for several graphs over the same repo")
    ap.add_argument("--path", action="append", default=[],
                    help="keep only the marks in this folder or file of the repo; repeat for more")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    parsed, failed = parse_files(args.repo)
    marks = extract_marks(parsed)
    if args.path:   # one slice: the marks of other slices are not findings of this one (second-project M-13)
        keep = [p.replace("\\", "/").strip("/") for p in args.path]
        marks = [m for m in marks if any(m["file"] == k or m["file"].startswith(k + "/") for k in keep)]
    graph_nodes, _, _, conflicts = load_graphs([g.read_text(encoding="utf-8") for g in args.graph])
    lifted, top_level, ambiguous = lift_calls(parsed, marks)
    findings, calls = diff(marks, graph_nodes, lifted, top_level, conflicts)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "extract.json").write_text(json.dumps(
        {"marks": marks, "graph_nodes": graph_nodes, "calls": calls, "top_level_sites": top_level,
         "findings": findings, "parse_failures": failed}, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "diff-report.md").write_text(
        render_report(findings, marks, graph_nodes, calls, top_level, ambiguous, failed), encoding="utf-8")
    print(f"marks={len(marks)} graph_nodes={len(graph_nodes)} calls={len(calls)} "
          f"findings={len(findings)} parse_failures={len(failed)}")


if __name__ == "__main__":
    main()
