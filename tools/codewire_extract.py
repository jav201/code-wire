"""Code-Wire DDR extractor: compare `# node:` marks in Python code with a Code-Wire graph (.md, format B).

Usage: python codewire_extract.py --repo <path> --graph <graph.md> --out <dir>

Reads the canonical text (v2.5, format B: one field per line, `type name`, `;` between inputs,
`X?` optional, `= default`), compares every node with the def its mark names, checks the edges
against the declared ports, and applies C15: each call between marked nodes, lifted to the
nearest marked node through unmarked helpers (O2, reflexion-style), must be declared in the
graph (`inner:` of the caller, or an edge between the two). Writes <out>/extract.json and
<out>/diff-report.md. Stdlib only.
v2.6: the section `## Boundary` gives edges to and from `[Outside: …]` items, and `discarded:` lines.
`codewire_coherence.py` uses them for C2, C3 and C4.
E7b: `parse_text` gives the full parse of `docs/Notation-Grammar.md` §8, with the warnings G1–G7 of §9.
`codewire_lint.py` writes it.
"""
import argparse
import ast
import json
import re
from pathlib import Path

MARK_RE = re.compile(r"^\s*#\s*node:\s*(\S+)\s*(?:\[([^\]]*)\])?")
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".dev-flow"}
NODE_KEYS = ("req", "in", "out", "func", "module", "modify", "inner", "open", "contract", "volatile", "oracle")  # and `examples:`
REPEAT_KEYS = ("examples", "oracle")   # a key that can have more than one line in a node
ENTITY_KEYS = ("in", "desc", "sequence", "offers")
OFFER = re.compile(r'^offers:\s*(\([^)]*\)\s*)?"([^"]+)"\s*→\s*(\S+)\s*$')
FINDING_KEYS = ("anchor", "seen", "cause", "effect", "decision")
SECTIONS = ("Nodes", "Entities", "Edges", "Boundary", "Routes", "Findings")
ROUTE_KEYS = ("route", "entry", "desc")
MARKERS = ("synthetic", "inferred")
CODE_NAME = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")
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
            "inner": [x.strip() for x in fields.get("inner", "").split(",") if x.strip()],
            "examples": examples,
            # `modify:` targets without their assignment kind: an entity `[...]` or an input path (Q28)
            "modify": [ASSIGN_RE.sub("", x).strip() for x in modify],
            "assign": [ASSIGN_RE.search(x).group(1) if ASSIGN_RE.search(x) else None for x in modify],
            "func": fields.get("func") or None,
            "open": fields.get("open") or None,
            "contract": fields.get("contract") or None,
            "volatile": [x.strip() for x in fields.get("volatile", "").split(",") if x.strip()],
            "oracle": oracle,
        })
    return nodes


def parse_entities(md_text):
    """Names of the `[Kind: name]` blocks declared in `## Entities`."""
    return [l.strip() for l in section(md_text, "Entities").splitlines() if l.strip().startswith("[")]


def parse_discarded(md_text):
    """`discarded: <node>.<output> — <reason>` lines of `## Boundary` (v2.6, §3.7)."""
    out = []
    for line in section(md_text, "Boundary").splitlines():
        m = re.match(r"\s*discarded:\s*(\S+)\s*(?:—|-)\s*(.*)$", line)
        if m:
            out.append({"port": m.group(1), "reason": m.group(2).strip()})
    return out


def load_graphs(texts):
    """Merge several graph files that share one repo: nodes by name (first wins, a different
    contract for the same name is reported), edges and entities concatenated.
    The edges of `## Boundary` (v2.6) are edges with `boundary: True`, and their `[Outside: …]`
    items are entities."""
    nodes, edges, entities, conflicts = {}, [], [], []
    for md in texts:
        file_nodes = parse_graph(md)
        for n in file_nodes:
            if n["name"] in nodes:
                a, b = nodes[n["name"]], n
                if (a["in"], a["out"]["type"], a["module"]) != (b["in"], b["out"]["type"], b["module"]):
                    conflicts.append(n["name"])
                else:  # same node seen by two flows: each brings its own thread
                    a["examples"] += [e for e in b["examples"] if e not in a["examples"]]
            else:
                nodes[n["name"]] = n
        entities += parse_entities(md)
    names = list(nodes)
    for md in texts:
        edges += parse_edges(md, names)
        outer = parse_edges(md, names, "Boundary")
        for e in outer:
            e["boundary"] = True
            entities += [ep["entity"] for ep in (e["src"], e["dst"]) if ep["entity"]]
        edges += outer
    return list(nodes.values()), edges, list(dict.fromkeys(entities)), conflicts


def parse_edges(md_text, node_names, title="Edges"):
    """Every `A ──▶ B` line of `## <title>`; a following `when:` line is attached to the edge.
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
    for line in section(md_text, title).splitlines():
        line = line.strip()
        if ARROW in line:
            src, dst = line.split(ARROW, 1)
            q = re.match(r"(\[\d+→\w+\])\s*", dst.strip())  # quantifier such as [1→N]
            dst = dst.strip()[q.end():] if q else dst
            edges.append({"src": endpoint(src), "dst": endpoint(dst), "quantifier": q.group(1) if q else None,
                          "when": None, "raw": line, "boundary": False})
        elif line.startswith("when:") and edges:
            edges[-1]["when"] = line[len("when:"):].strip()
    return edges


# ---------- full parse and warnings (Notation-Grammar.md §8, §9) ----------

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


def parse_routes(md_text):
    """The `route:` blocks of `## Routes`: name, entries, desc (Notation-Grammar.md §6.1)."""
    out = []
    for block in numbered_blocks(numbered_sections(md_text).get("Routes", [])):
        r = {"name": None, "entries": [], "desc": None}
        for _, line in block:
            m = re.match(r"(\w+):\s*(.*)$", line.strip())
            if not m:
                continue
            if m.group(1) == "route" and r["name"] is None:
                r["name"] = m.group(2).strip() or None
            elif m.group(1) == "entry" and not r["entries"]:
                r["entries"] = [e.strip() for e in split_entries(m.group(2)) if e.strip()]
            elif m.group(1) == "desc" and r["desc"] is None:
                r["desc"] = m.group(2).strip() or None
        if r["name"]:
            out.append(r)
    return out


def split_entries(text):
    """Split at each comma that is not inside `[ … ]` (an entity name can hold a comma)."""
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "["
        depth -= ch == "]"
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur]


def example_source(line):
    """The source in the parentheses of an `examples:` line: {thread, step, root, marker}.
    `(T1, t1a)`, `(U2, U2.4, root TuiApp.on_button_pressed)`, `(synthetic)`, `(T-8, inferred)`."""
    src = {"thread": None, "step": None, "root": None, "marker": None}
    m = re.match(r"\s*\(([^)]*)\)", line)
    if not m:
        return src
    for i, part in enumerate(p.strip() for p in m.group(1).split(",")):
        word = part.split(" ")[0]
        if part in MARKERS:
            src["marker"] = part
        elif word == "root" and len(part.split()) == 2:
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


def graph_warnings(md_text):
    """The warnings G1–G7 of Notation-Grammar.md §9: [{code, line, text}], in the order of the lines."""
    secs = numbered_sections(md_text)
    names = [n["name"] for n in parse_graph(md_text)]
    entities = set(parse_entities(md_text)) | {ep["entity"] for e in parse_edges(md_text, names, "Boundary")
                                               for ep in (e["src"], e["dst"]) if ep["entity"]}
    w = []

    def warn(code, line, text):
        w.append({"code": code, "line": line, "text": text})

    def known(end, declared_only):
        end = re.sub(r"^\[\d+→\w+\]\s*", "", end.strip())
        e = ENTITY_END.match(end)
        if e:
            return not declared_only or e.group(1) in entities
        return any(end == n or end.startswith(n + ".") for n in names)

    def fields(block, keys, where, twice):
        seen = set()
        for i, line in block[1:]:
            f = re.match(r"(\w+):", line)
            key = f.group(1) if f else None
            if key not in keys:
                warn("G2", i, f"`{line.strip()[:40]}` in {where}: not a field of the grammar")
            elif key in seen and twice and key not in REPEAT_KEYS:  # one `examples:` line for each pair
                warn("G3", i, f"`{key}:` two times in {where}: the second line is skipped")
            seen.add(key)
        return seen

    for i, line in enumerate(md_text.splitlines(), 1):
        m = re.match(r"## (.*?)\s*$", line)
        if m and m.group(1) not in SECTIONS:
            warn("G1", i, f"section `{m.group(1)}` is not part of the graph")
    for block in numbered_blocks(secs.get("Nodes", [])):
        i, first = block[0][0], block[0][1].strip()
        if first.startswith("[") or ":" in first:
            warn("G7", i, f"`{first[:40]}`: a block in `## Nodes` with no name line")
        elif not {"in", "out"} & fields(block, NODE_KEYS + ("examples",), f"node `{first}`", True):
            warn("G7", i, f"node `{first}` has no `in:` and no `out:`")
        else:
            node_fields(block, first, warn)
    for block in numbered_blocks(secs.get("Entities", [])):
        rest = [(i, l) for i, l in block if not re.match(r"\s+\w+:", l)]  # the lines under `sequence:`
        if block[0][1].startswith("["):
            fields(rest, ENTITY_KEYS, f"entity `{block[0][1].strip()}`", False)
            for i, line in rest:
                if not line.strip().startswith("offers:"):
                    continue
                o = OFFER.match(line.strip())
                if not o:
                    warn("G9", i, f"`{line.strip()[:50]}`: not of the form offers: (source) \"control\" → node")
                elif not block[0][1].startswith("[Interface:"):
                    warn("G9", i, f"`offers:` on `{block[0][1].strip()}`, which is not an `[Interface]` entity")
                elif o.group(3) not in names:
                    warn("G9", i, f"offer `{o.group(2)}`: `{o.group(3)}` is not a node of `## Nodes`")
    for title in ("Edges", "Boundary"):
        edge_before = False
        for i, line in secs.get(title, []):
            s = line.strip()
            if ARROW in s:
                edge_before = True
                for end in s.split(ARROW, 1):
                    end = re.sub(r"^\[\d+→\w+\]\s*", "", end.strip())
                    e = ENTITY_END.match(end)
                    if e and e.group(2).strip() and not FIELD.match(e.group(2).strip()):
                        warn("G12", i, f"`{end}`: after the entity, `{e.group(2).strip()}` is not `.` and a name")
                    elif not known(end, False):
                        warn("G4", i, f"`{end}` is not a node, a port of a node or an entity")
            elif s.startswith("when:") and not edge_before:
                warn("G5", i, "`when:` with no edge before it")
    for block in numbered_blocks(secs.get("Routes", [])):
        i, first = block[0][0], block[0][1].strip()
        fields(block, ROUTE_KEYS, f"route `{first[:40]}`", True)
        entry = [l for _, l in block if l.strip().startswith("entry:")]
        if not entry or not entry[0].split(":", 1)[1].strip():
            warn("G8", i, f"`{first[:40]}`: a route with no `entry:`")
            continue
        for e in split_entries(entry[0].split(":", 1)[1]):
            e = e.strip()
            if not (e in names or (e.startswith("[Outside:") and e in entities) or CODE_NAME.match(e)):
                warn("G8", i, f"entry `{e}` is not a node, an `[Outside: …]` item of `## Boundary` or a code name")
    for block in numbered_blocks(secs.get("Findings", [])):
        i, first = block[0][0], block[0][1].strip()
        if not re.match(r"finding\s+\S+", first):
            warn("G7", i, f"`{first[:40]}`: a block in `## Findings` with no `finding` line")
            continue
        fields(block, FINDING_KEYS, f"finding `{first.split()[1]}`", True)
        for j, line in block[1:]:
            a = re.match(r"anchor:\s*(.*)$", line)
            if a and not all(known(end, True) for end in a.group(1).split(ARROW)):
                warn("G6", j, f"anchor `{a.group(1).strip()}` is not in the graph")
    return sorted(w, key=lambda x: x["line"])


def node_fields(block, name, warn):
    """G10 and G11: a `volatile:` item must start with an input, an output name or `out`; an `oracle:` line
    must name a source."""
    value = lambda key: next((l.split(":", 1)[1].strip() for _, l in block if l.startswith(key + ":")), "")  # noqa: E731
    ins = {parse_decl(x)["name"] for x in split_top(value("in"), ";") if x.strip()}
    outs = set(parse_out(value("out"))["names"]) | {"out"}
    for i, line in block[1:]:
        if line.startswith("volatile:"):
            for item in (x.strip() for x in line.split(":", 1)[1].split(",")):
                if item.split(".")[0] not in ins | outs:
                    warn("G10", i, f"volatile `{item}` of `{name}`: not an input, an output or `out`")
        elif line.startswith("oracle:") and not line.split(":", 1)[1].strip():
            warn("G11", i, f"an empty `oracle:` line in `{name}`")


def parse_text(md_text):
    """The full parse of one graph text, in the shape of Notation-Grammar.md §8."""
    nodes, edges, entities, _ = load_graphs([md_text])
    blocks = {e["name"]: e for e in parse_entity_blocks(md_text)}
    end = lambda p: {k: p[k] for k in ("node", "port", "entity", "field")}  # noqa: E731
    return {
        "nodes": [{"name": n["name"], "reqs": n["reqs"], "in": n["in"], "out": n["out"], "func": n["func"],
                   "module": n["module"], "examples": n["examples"],
                   "modify": [{"target": t, "assign": a} for t, a in zip(n["modify"], n["assign"])],
                   "inner": n["inner"], "open": n["open"], "contract": n["contract"],
                   "volatile": n["volatile"], "oracle": n["oracle"]} for n in nodes],
        "entities": [blocks.get(e, {"name": e, "kind": entity_kind(e), "in": None, "desc": None, "sequence": [], "offers": []})
                     for e in entities],
        "edges": [{"src": end(e["src"]), "dst": end(e["dst"]), "quantifier": e["quantifier"], "when": e["when"],
                   "boundary": e["boundary"], "raw": e["raw"]} for e in edges],
        "discarded": parse_discarded(md_text),
        "routes": parse_routes(md_text),
        "findings": parse_findings(md_text),
        "warnings": graph_warnings(md_text),
    }


# ---------- C15: call resolution and O2 lifting ----------

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


def diff(marks, graph_nodes, edges, lifted, top_level, entities=None, conflicts=()):
    findings = []

    def add(kind, where, msg):
        findings.append({"kind": kind, "where": where, "msg": msg})

    for name in conflicts:
        add("graph_node_conflict", name, f"`{name}` is declared in two graph files with different contracts")
    # C10 (with Q28): every `modify:` target is a declared entity or one of the node's own inputs
    for node in graph_nodes:
        inputs = {p["name"] for p in node["in"]}
        for target in node.get("modify", []):
            if target.startswith("["):
                if entities is not None and target not in entities:
                    add("modify_unknown_target", node["name"], f"`{target}` in `modify:` of `{node['name']}` is not a declared entity")
            elif re.split(r"[.\[]", target)[0] not in inputs:
                add("modify_unknown_target", node["name"], f"`{target}` in `modify:` of `{node['name']}` is neither an entity nor an input")

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

        if node["reqs"] is None:
            add("graph_req_field_missing", where, f"`{node['name']}` has no `req:` in the graph")
        elif m["reqs"] is None or sorted(m["reqs"]) != sorted(node["reqs"]):
            add("req_mismatch", where, f"mark {m['reqs']} vs graph {node['reqs']}")

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

    # edges: endpoints must exist; a port must be an input or output of its node
    linked = set()
    for e in edges:
        for side in ("src", "dst"):
            ep = e[side]
            if ep.get("unknown"):
                add("edge_unknown_endpoint", e["raw"], f"`{ep['unknown']}` is neither an entity nor a graph node")
            elif ep["node"] and ep["port"]:
                n = nodes[ep["node"]]
                ports = {p["name"] for p in n["in"]} | set(n["out"]["names"])
                if ep["port"].split(".")[0] not in ports:
                    add("edge_unknown_port", e["raw"], f"`{ep['port']}` is not an input or output of `{ep['node']}`")
        if e["src"]["node"] and e["dst"]["node"]:
            linked.add(frozenset((e["src"]["node"], e["dst"]["node"])))

    # C15: lifted calls against interior: or an edge between the two nodes
    c15 = []
    for (x, y), sites in sorted(lifted.items()):
        if x in nodes and y in nodes[x]["inner"]:
            via = "inner"
        elif frozenset((x, y)) in linked:
            via = "edge"
        else:
            via = None
            also = top_level.get(y)
            note = ""
            if also:
                more = f" (+{len(also) - 5} more)" if len(also) > 5 else ""
                note = f"; also called at top level: {', '.join(also[:5])}{more}"
            add("c15_divergence", sites[0], f"`{x}` → `{y}` (sites: {', '.join(sites)}) not declared in `inner:` of `{x}` nor as an edge{note}")
        c15.append({"caller": x, "callee": y, "sites": sites, "declared_via": via})
    owners = {}
    for name, n in nodes.items():
        for y in n["inner"]:
            owners.setdefault(y, []).append(name)
            if y not in nodes:
                add("interior_unknown_node", name, f"`{y}` in `inner:` of `{name}` is not a graph node")
            elif (name, y) not in lifted:
                add("info_c15_absence", name, f"`inner:` of `{name}` declares `{y}`, no lifted call found")
    for y, who in owners.items():
        if len(who) > 1:
            add("info_declared_in_two_interiors", y, f"`{y}` declared inside {', '.join(f'`{w}`' for w in who)}: two call sites by design")
    return findings, c15


KIND_TITLES = {
    "graph_node_without_mark": "Graph node without mark",
    "mark_without_graph_node": "Mark without graph node",
    "duplicate_mark": "Same node marked twice",
    "dangling_mark": "Mark not bound to a def",
    "mark_name_ne_qualname": "Mark name differs from def qualname",
    "module_mismatch": "Module/file mismatch",
    "req_mismatch": "Requirement trace mismatch (mark vs graph)",
    "graph_req_field_missing": "Graph node has no `req:` field",
    "graph_examples_missing": "Graph node has no `examples:` (required field, §3.1)",
    "graph_node_conflict": "Same node declared with different contracts in two graph files",
    "modify_unknown_target": "`modify:` target is neither a declared entity nor an input (C10, Q28)",
    "input_missing_in_code": "Input in graph, not a parameter in code",
    "input_missing_in_graph": "Parameter in code, not an input in graph",
    "input_type_mismatch": "Input type mismatch",
    "input_untyped_in_graph": "Input untyped in graph (cannot compare)",
    "input_untyped_in_code": "Parameter unannotated in code (cannot compare)",
    "default_mismatch": "Default value mismatch (C12)",
    "output_type_mismatch": "Output type mismatch",
    "output_untyped_in_code": "Return unannotated in code (cannot compare)",
    "edge_unknown_endpoint": "Edge endpoint is not a node or entity",
    "edge_unknown_port": "Edge port is not an input or output of its node",
    "interior_unknown_node": "`inner:` names an unknown node",
    "c15_divergence": "C15 divergence: lifted call not declared in the graph",
    "info_type_loose": "Info: graph names the bare container only (loose match)",
    "info_c15_absence": "Info: declared in `inner:`, no lifted call found (C15 absence)",
    "info_declared_in_two_interiors": "Info: node declared in two `inner:` lists",
}


def render_report(findings, marks, graph_nodes, edges, c15, top_level, ambiguous, failed):
    drift = sum(not f["kind"].startswith("info_") for f in findings)
    out = ["# Code-Wire DDR diff report", "",
           f"- Marks found: {len(marks)}",
           f"- Graph nodes parsed: {len(graph_nodes)} · edges: {len(edges)} ({sum(1 for e in edges if e['when'])} with `when:`)",
           f"- Nodes with `examples:`: {sum(1 for n in graph_nodes if n['examples'])}/{len(graph_nodes)} "
           f"({sum(len(n['examples']) for n in graph_nodes)} pairs)",
           f"- Lifted calls between marked nodes (O2): {len(c15)} "
           f"({sum(1 for c in c15 if c['declared_via'])} declared, {sum(1 for c in c15 if not c['declared_via'])} divergent)",
           f"- Findings: {len(findings)} ({drift} drift, {len(findings) - drift} info)",
           f"- Ambiguous call resolutions (a name matched several defs): {ambiguous}",
           f"- Files that failed to parse: {len(failed)}", "",
           "Type normalisation: spaces and quotes dropped; `List/Dict/Tuple/Set` -> builtins; "
           "`X | None` and graph `X?` -> `Optional[X]`; graph `(Callable) A->B` -> `Callable[[A], B]`; graph "
           "`tuple(A a, B b)` -> `tuple[A, B]`. A bare graph container (`dict`) against a parameterised code "
           "type (`dict[str, Any]`), at top level or nested, is info (loose match), not drift.", "",
           "Call resolution is name-based (`f()`, `Class()` -> `__init__`, `self.m()`, `x.m()` -> top-level `m` "
           "or a marked method `m`); dynamic calls and callables passed as values are not seen. Tests excluded.", "",
           "## Counts", "", "| Kind | Count |", "|---|---|"]
    kinds = [k for k in KIND_TITLES if any(f["kind"] == k for f in findings)]
    for k in kinds:
        out.append(f"| {KIND_TITLES[k]} | {sum(f['kind'] == k for f in findings)} |")
    out += ["", "## C15 · lifted calls (O2)", "", "| Caller | Callee | Sites | Declared via |", "|---|---|---|---|"]
    for c in c15:
        out.append(f"| `{c['caller']}` | `{c['callee']}` | {', '.join(c['sites'])} | {c['declared_via'] or '**divergence**'} |")
    if top_level:
        out += ["", "Top-level sites (orchestration with no marked node above):", ""]
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
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    parsed, failed = parse_files(args.repo)
    marks = extract_marks(parsed)
    graph_nodes, edges, entities, conflicts = load_graphs([g.read_text(encoding="utf-8") for g in args.graph])
    lifted, top_level, ambiguous = lift_calls(parsed, marks)
    findings, c15 = diff(marks, graph_nodes, edges, lifted, top_level, entities, conflicts)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "extract.json").write_text(json.dumps(
        {"marks": marks, "graph_nodes": graph_nodes, "edges": edges, "c15": c15, "top_level_sites": top_level,
         "findings": findings, "parse_failures": failed}, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "diff-report.md").write_text(
        render_report(findings, marks, graph_nodes, edges, c15, top_level, ambiguous, failed), encoding="utf-8")
    print(f"marks={len(marks)} graph_nodes={len(graph_nodes)} edges={len(edges)} lifted={len(c15)} "
          f"findings={len(findings)} parse_failures={len(failed)}")


if __name__ == "__main__":
    main()
