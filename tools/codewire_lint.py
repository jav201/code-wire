"""Code-Wire lint: read one graph text (format B) in full and list the warnings of `docs/Notation-Grammar.md` §9.

Usage: python codewire_lint.py GRAPH.md [--json parse.json]

Prints one line for each warning (`file:line: code text`). With `--json`, writes the full parse in the
shape of Notation-Grammar.md §8. A warning does not stop the lint: the tools skip that line.
Exit code 1 only when the lint cannot read a block (G7) or the text has no node. Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codewire_extract as cw  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("graph", type=Path)
    ap.add_argument("--json", type=Path, help="write the full parse to this file")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")  # a console with no `──▶` must not stop the lint
    parse = cw.parse_text(a.graph.read_text(encoding="utf-8"))
    if a.json:
        a.json.write_text(json.dumps(parse, indent=2, ensure_ascii=False), encoding="utf-8")
    for w in parse["warnings"]:
        print(f"{a.graph}:{w['line']}: {w['code']} {w['text']}")
    unread = sum(w["code"] == "G7" for w in parse["warnings"])
    print(f"nodes={len(parse['nodes'])} entities={len(parse['entities'])} edges={len(parse['edges'])} "
          f"findings={len(parse['findings'])} warnings={len(parse['warnings'])} unread blocks={unread}")
    if not parse["nodes"]:
        print("no node: the text has no block in `## Nodes` that the lint can read")
    return 1 if unread or not parse["nodes"] else 0


if __name__ == "__main__":
    sys.exit(main())
