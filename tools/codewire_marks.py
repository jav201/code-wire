"""Code-Wire generated marks (decision D3): write the `# node:` marks from the graph text into a
throwaway worktree, so the text stays the only source (C14) and nothing has to be rebased when the
code moves.

For every node, the def named by the node (qualname) in its `module:` file gets
`# node: <name>  [<req>, ...]` on the line above it (above its decorators, same indentation),
exactly what `codewire_extract.extract_marks` reads. A node whose file or def is gone is reported,
not guessed: in a snapshot that is "node without code". Before writing, the marks of the previous
run are removed with `git checkout` on the touched files; if the worktree has any change that is not
an added mark line, nothing is touched (DirtyWorktree).

    python codewire_marks.py --repo <worktree> --graph G1.md [--graph G2.md] [--out marks.json]
"""
import argparse
import ast
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codewire_extract as cw  # noqa: E402


class DirtyWorktree(RuntimeError):
    pass


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def clear_previous_marks(repo):
    """Revert the files changed by an earlier run; refuse if anything else changed."""
    changed = [l for l in git(repo, "diff", "--name-only").splitlines() if l.strip()]
    if not changed:
        return
    for line in git(repo, "diff", "-U0").splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("-") or (line.startswith("+") and not cw.MARK_RE.match(line[1:])):
            raise DirtyWorktree(f"worktree has changes other than marks: {line[:80]!r}")
    git(repo, "checkout", "--", *changed)


def mark_line(node, indent):
    reqs = node["reqs"]
    return " " * indent + f"# node: {node['name']}" + ("" if reqs is None else f"  [{', '.join(reqs)}]")


def emit(repo, nodes):
    """Write the marks; return (placed, missing)."""
    repo = Path(repo)
    clear_previous_marks(repo)
    by_file, missing = defaultdict(list), []
    for n in nodes:
        rel = n["module"]
        path = repo / rel if rel else None
        if not path or not path.is_file():
            missing.append({"name": n["name"], "module": rel, "why": "no file"})
            continue
        by_file[rel].append(n)
    placed = []
    for rel, file_nodes in by_file.items():
        path = repo / rel
        raw = path.read_bytes().decode("utf-8")
        nl = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.split(nl)
        defs = {q: fn for q, fn, _ in cw.defs_with_qualnames(ast.parse(raw))}
        inserts = []
        for n in file_nodes:
            fn = defs.get(n["name"])
            if fn is None:
                missing.append({"name": n["name"], "module": rel, "why": "no def"})
                continue
            first = min([fn.lineno] + [d.lineno for d in fn.decorator_list])
            inserts.append((first, mark_line(n, fn.col_offset), n["name"]))
        for first, text, _ in sorted(inserts, reverse=True):
            lines.insert(first - 1, text)
        path.write_bytes(nl.join(lines).encode("utf-8"))
        # line numbers after insertion: each mark shifts the ones below it by one
        for i, (first, _, name) in enumerate(sorted(inserts)):
            placed.append({"name": name, "file": rel, "line": first + i})
    order = {n["name"]: i for i, n in enumerate(nodes)}
    placed.sort(key=lambda m: order[m["name"]])
    return placed, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--graph", required=True, type=Path, action="append")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    nodes, _, _, conflicts = cw.load_graphs([g.read_text(encoding="utf-8") for g in a.graph])
    placed, missing = emit(a.repo, nodes)
    if a.out:
        a.out.write_text(json.dumps({"placed": placed, "missing": missing, "conflicts": conflicts}, indent=1), encoding="utf-8")
    print(f"{len(placed)} marks written, {len(missing)} nodes without code" + (f", conflicts {conflicts}" if conflicts else ""))
    for m in missing:
        print(f"  missing: {m['name']} ({m['module']}): {m['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
