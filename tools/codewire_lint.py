"""Code-Wire lint: list the lines of a graph text (format B) that the parser does not read.

Usage: python codewire_lint.py GRAPH.md [--json parse.json]

A tool skips such a line with no word, so each one is an error: exit code 1. With `--json`, it also
writes the full parse (Notation-Grammar.md). Stdlib only.
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
    for w in parse["unread"]:
        print(f"{a.graph}:{w['line']}: not read: {w['text']}")
    print(f"nodes={len(parse['nodes'])} entities={len(parse['entities'])} edges={len(parse['edges'])} "
          f"findings={len(parse['findings'])} not read={len(parse['unread'])}")
    if not parse["nodes"]:
        print("no node: the text has no block in `## Nodes` that the parser can read")
    return 1 if parse["unread"] or not parse["nodes"] else 0


if __name__ == "__main__":
    sys.exit(main())
