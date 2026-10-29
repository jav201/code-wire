"""The gates of the review by modules (docs/Review-Method.md): brief, map-gate, review-gate.

A work folder holds `base/` (the code and the canon grouped in chapters), one copy per group, `groups.csv`
(`id,group`) and `files.csv` (`file,group`). Each command exits 1 and says why when a step is skipped or a
gate fails, so no agent and no orchestrator can go on from a state that was not checked.
"""
import argparse
import ast
import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codewire_extract as cw  # noqa: E402

TOOLS = Path(__file__).resolve().parent
SKIP = {"_map", "_review", ".git", "__pycache__", ".pytest_cache"}
# a test that fails like this did not reach the code it reviews
ENV_FAILURE = r"not natively supported|ERROR collecting|ModuleNotFoundError|ImportError while importing"


class Work:
    def __init__(self, root):
        self.root = Path(root)
        self.base = self.root / "base"
        self.group_of = {r["id"]: r["group"] for r in csv.DictReader(open(self.root / "groups.csv", encoding="utf-8"))}
        self.files = {}
        for r in csv.DictReader(open(self.root / "files.csv", encoding="utf-8")):
            self.files.setdefault(r["group"], []).append(r["file"].replace("\\", "/"))
        canon = (self.base / "REQUIREMENTS.md").read_text(encoding="utf-8")
        self.status = {}
        for line in canon.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else []
            if cells and cells[0] in self.group_of:
                self.status[cells[0]] = cells[-1]
        self.names = dict(re.findall(r"^## (\S+) — (.+)$", canon, re.M))

    def groups(self):
        return [g for g in self.files]

    def graph(self, g):
        return self.root / g / "_map" / f"graph-{g}.md"

    def passed(self, g):
        return (self.root / g / "_map" / "MAP-GATE.ok").exists()


def defs(path):
    """Functions and methods by qualname; a function nested inside another is part of its parent."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [q for q, _, _ in cw.defs_with_qualnames(tree) if "<locals>" not in q]


def node_blocks(text):
    """(name, module, block text, req ids, example sources) for each node block, same names in two modules kept apart."""
    out = []
    for block in re.split(r"\n\s*\n", cw.section(text, "Nodes")):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines or ":" in lines[0].split()[0] or lines[0].lstrip().startswith(("###", ">")):
            continue
        keys = dict(re.findall(r"^(\w+):\s*(.*)$", block, re.M))
        reqs = [] if keys.get("req", "").strip() in ("", "to trace") else [x.strip() for x in keys["req"].split(",")]
        srcs = [cw.example_source(l.split(":", 1)[1])["thread"] or "" for l in lines if l.startswith("examples:")]
        out.append((lines[0].strip(), keys.get("module", "").strip().replace("\\", "/"), block.strip(), reqs, srcs))
    return out


def test_ids(root):
    ids = set()
    for p in (root / "tests").rglob("test_*.py"):
        rel, tree = p.relative_to(root).as_posix(), ast.parse(p.read_text(encoding="utf-8"))
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
                ids.add(f"{rel}::{n.name}")
            elif isinstance(n, ast.ClassDef):
                ids |= {f"{rel}::{n.name}::{m.name}" for m in n.body
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith("test")}
    return ids


def changed(copy, base):
    """Files of the copy that differ from base outside `_map/` and `_review/`; a `# node:` comment line does not count."""
    def strip(p):
        return [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if not l.strip().startswith("# node:")]
    out = []
    for p in copy.rglob("*"):
        rel = p.relative_to(copy)
        if p.is_dir() or SKIP & set(rel.parts):
            continue
        b = base / rel
        if not b.exists() or (p.read_bytes() != b.read_bytes() and strip(p) != strip(b)):
            out.append(rel.as_posix())
    out += [p.relative_to(base).as_posix() for p in base.rglob("*")
            if p.is_file() and not SKIP & set(p.relative_to(base).parts) and not (copy / p.relative_to(base)).exists()]
    return sorted(out)


def check_map(w, g):
    text = w.graph(g).read_text(encoding="utf-8")
    blocks = node_blocks(text)
    have = {(m, n) for n, m, *_ in blocks}
    code = {(f, q) for f in w.files[g] for q in defs(w.base / f)}
    tids = test_ids(w.base)
    problems = [f"line {u['line']} not read: {u['text']}" for u in cw.unread(text)]
    problems += [f"no node for {f}::{q}" for f, q in sorted(code - have)]
    problems += [f"{n}: requirement id {r} does not exist" for n, _, _, rs, _ in blocks for r in rs if r not in w.group_of]
    problems += [f"{n}: cited test {s} does not exist" for n, _, _, _, ss in blocks for s in ss
                 if s and s != "untested" and s.replace("\\", "/") not in tids]
    problems += [f"changed outside _map/: {p}" for p in changed(w.root / g, w.base)]
    return problems, blocks


def regenerate(w):
    """TRACES.md and cross-nodes.md for every group whose map passed, from all the passed maps."""
    maps = {g: node_blocks(w.graph(g).read_text(encoding="utf-8")) for g in w.groups() if w.passed(g)}
    for g, blocks in maps.items():
        chapter = sorted(i for i, gg in w.group_of.items() if gg == g and w.status.get(i, "").startswith("active"))
        here = {r for *_, rs, _ in blocks for r in rs}
        elsewhere = {r: o for o, bs in maps.items() if o != g for *_, rs, _ in bs for r in rs}
        cross = [(o, b) for o, bs in maps.items() if o != g for _, _, b, rs, _ in bs if set(rs) & set(chapter)]
        lines = [f"# Traces — {g} (generated by codewire_review.py; notes of the orchestrator go below the last line)", "",
                 f"- Nodes: {len(blocks)}; `to trace`: {sum(1 for *_, rs, _ in blocks if not rs)}; "
                 f"untested: {sum(1 for *_, ss in blocks if 'untested' in ss)}.",
                 f"- Active rows of the chapter: {len(chapter)}; with a node here: {len(here & set(chapter))}.",
                 "- Rows whose nodes are in another module (this chapter owns their review; the nodes are in "
                 "`cross-nodes.md`): " + (", ".join(f"{r} ({elsewhere[r]})" for r in chapter if r not in here and r in elsewhere) or "none") + ".",
                 "- Rows with no node in any passed map: " + (", ".join(r for r in chapter if r not in here and r not in elsewhere) or "none") + ".",
                 f"- Maps included: {', '.join(sorted(maps))}.", ""]
        (w.root / g / "_map" / "TRACES.md").write_text("\n".join(lines), encoding="utf-8")
        body = [f"# Nodes of other modules that carry a requirement of {g}", ""] + [f"<!-- from {o} -->\n{b}\n" for o, b in cross]
        (w.root / g / "_map" / "cross-nodes.md").write_text("\n".join(body), encoding="utf-8")


def fresh(w, g):
    traces = w.root / g / "_map" / "TRACES.md"
    return traces.exists() and all(traces.stat().st_mtime >= w.graph(o).stat().st_mtime for o in w.groups() if w.passed(o))


def cmd_map_gate(w, a):
    problems, _ = check_map(w, a.group)
    for p in problems:
        print("FAIL", p)
    if problems:
        return 1
    (w.root / a.group / "_map" / "MAP-GATE.ok").write_text("passed\n", encoding="utf-8")
    regenerate(w)
    print(f"PASS map {a.group}; traces and cross nodes rewritten for {', '.join(g for g in w.groups() if w.passed(g))}")
    return 0


def cmd_review_gate(w, a):
    g, problems = a.group, []
    tests = w.root / g / "_review" / "code" / "tests"
    if not tests.exists():
        problems.append("no code-review tests in _review/code/tests")
    else:
        # -B and a fresh prefix: a gate that reads a stale .pyc of an edited test would judge old code
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": str(w.root / ".gate-pyc" / g)}
        env.pop("NO_COLOR", None)
        if a.pythonpath:   # run the tests the way the reviewer did (a plugin kept under _review/, for example)
            env["PYTHONPATH"] = os.pathsep.join([str(w.root / g / a.pythonpath), env.get("PYTHONPATH", "")])
        shutil.rmtree(w.root / ".gate-pyc" / g, ignore_errors=True)
        run = subprocess.run([a.python, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *a.pytest_arg,
                              "_review/code/tests"], cwd=w.root / g, capture_output=True, text=True,
                             timeout=a.timeout, env=env)
        failed = re.search(r"(\d+) failed", run.stdout)
        print(run.stdout.strip().splitlines()[-1] if run.stdout.strip() else run.stderr.strip()[-300:])
        if re.search(ENV_FAILURE, run.stdout + run.stderr):
            problems.append("the code-review tests fail for their environment, not for a defect "
                            "(run them as the reviewer did: --pytest-arg / --pythonpath)")
        elif not failed:
            problems.append("no code-review test fails on the current code")
    for copy in (w.root / g, w.root / f"{g}-tests"):
        if copy.exists():
            problems += [f"{copy.name}: product file changed: {p}" for p in changed(copy, w.base)]
    for p in problems:
        print("FAIL", p)
    if problems:
        return 1
    (w.root / g / "_review" / "REVIEW-GATE.ok").write_text("passed\n", encoding="utf-8")
    print(f"PASS review {g}")
    return 0


def cmd_brief(w, a):
    g, kind = a.group, a.kind
    if kind in ("code", "tests"):
        if not w.passed(g):
            print(f"FAIL the map of {g} has not passed map-gate")
            return 1
        if not fresh(w, g):
            print(f"FAIL the traces of {g} are older than a passed map: run map-gate again")
            return 1
    if kind == "cohesion":
        missing = [x for x in w.groups() if not (w.root / x / "_review" / "REVIEW-GATE.ok").exists()]
        if missing:
            print(f"FAIL review-gate not passed for: {', '.join(missing)}")
            return 1
    if kind == "map" and not (w.root / g).exists():
        shutil.copytree(w.base, w.root / g, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    if kind == "tests":
        target = w.root / f"{g}-tests"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(w.root / g, target, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "_review"))
    parts = dict(re.findall(r"^=== (\w+)\n(.*?)(?=^=== |\Z)", (TOOLS / "review_briefs.md").read_text(encoding="utf-8"), re.S | re.M))
    text = parts[kind]
    for k, v in {"{WORK}": str(w.root), "{G}": g or "", "{NAME}": w.names.get(g, ""), "{PYTHON}": a.python,
                 "{TOOLS}": str(TOOLS), "{ENV}": a.env, "{FILES}": ", ".join(w.files.get(g, []))}.items():
        text = text.replace(k, v)
    out = w.root / "briefs" / f"{kind}-{g or 'all'}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text.strip() + "\n", encoding="utf-8")
    print(out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("brief", "map-gate", "review-gate"))
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--group", default="")
    ap.add_argument("--kind", choices=("map", "code", "tests", "cohesion"))
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--env", default="", help="environment notes written into the brief")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--pytest-arg", action="append", default=[], help="review-gate: one more pytest argument; repeat")
    ap.add_argument("--pythonpath", default="", help="review-gate: a folder of the group copy put on PYTHONPATH")
    a = ap.parse_args(argv)
    w = Work(a.work)
    return {"brief": cmd_brief, "map-gate": cmd_map_gate, "review-gate": cmd_review_gate}[a.command](w, a)


if __name__ == "__main__":
    sys.exit(main())
