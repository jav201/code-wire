"""Tests: the extractor and C16 exit 1 when a line of "done" does not hold.

Why these matter: the method says "done = each example holds and the extractor has no drift", and
agents read the exit code, not the report. In second-project batch 009 the cheap checks were green while problems
were open, and in the F6 test C16 gave a false ok. A tool that writes a drift into its report and exits
0 lets an agent say "no drift" with a green run. So each state that is not a held line exits 1. A line
with no recording at all stays 0: a regression test can be its proof, and the report puts it first.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_examples as ce  # noqa: E402
import codewire_extract as cw  # noqa: E402

CODE = "# node: twice  [R-1]\ndef twice(x: int) -> int:\n    return x * 2\n"
NODE = "## Nodes\n\ntwice\nreq: R-1\nin: {typ} x\nout: int y\nmodule: m.py\nexamples: (T) x `2` → `4`\n"


@pytest.mark.parametrize("typ,want", [("int", 0), ("str", 1)], ids=["same contract", "drift"])
def test_the_extractor_exits_1_on_drift(tmp_path, typ, want):
    (tmp_path / "m.py").write_text(CODE, encoding="utf-8")
    g = tmp_path / "g.md"
    g.write_text(NODE.format(typ=typ), encoding="utf-8")
    assert cw.main(["--repo", str(tmp_path), "--graph", str(g), "--out", str(tmp_path / "out")]) == want


def c16(tmp_path, line, trace):
    g = tmp_path / "g.md"
    g.write_text(f"## Nodes\n\ntwice\nin: int x\nout: int y\nexamples: {line}\n", encoding="utf-8")
    t = tmp_path / "t.json"
    t.write_text(json.dumps(trace), encoding="utf-8")
    return ce.main(["--graph", str(g), "--trace", f"T={t}", "--out", str(tmp_path / "c16.md")])


CALL = {"in": {"x": 2}, "out": 4}
CASES = [
    ("ok", "(T) x `2` → `4`", {"twice": [CALL]}, 0),
    ("drift", "(T) x `2` → `5`", {"twice": [CALL]}, 1),
    ("no_def", "(T) x `2` → `4`", {"_skipped": ["twice"]}, 1),
    ("node_not_run", "(T) x `2` → `4`", {}, 1),
    ("no_anchor", "(T) doubles the input", {"twice": [CALL]}, 1),
    ("not_checkable", "(T) an empty input → expect none", {"twice": [CALL]}, 1),
    ("no_trace", "(U) x `2` → `4`", {"twice": [CALL]}, 0),
]


@pytest.mark.parametrize("status,line,trace,want", CASES, ids=[c[0] for c in CASES])
def test_c16_exits_1_on_each_line_that_does_not_hold(tmp_path, status, line, trace, want):
    assert c16(tmp_path, line, trace) == want
    assert f"| {status} |" in (tmp_path / "c16.md").read_text(encoding="utf-8")
