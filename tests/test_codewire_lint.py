"""Tests for the full parse and the lines that the parser does not read (`codewire_lint.py`).

Why these matter: a line that the parser does not read leaves the graph with no word. A key with a wrong
letter (`fucn:`), a section with another title, or two merged blocks went out of the graph, and no tool
said so. In a data-flow audit, two merged blocks lost a node from the recording. So each such line is an
error, on its own line number, and the lint exits with code 1. The graphs of the guide are correct:
they have no such line, and the parse keeps each field.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import codewire_extract as cw  # noqa: E402
import codewire_lint as lint  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
GUIDE = sorted(FIXTURES.glob("guide-*.md"))
LESSON6 = (FIXTURES / "guide-lesson6.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("path", GUIDE, ids=[p.stem for p in GUIDE])
def test_the_guide_graphs_have_no_line_that_is_not_read(path):
    assert cw.unread(path.read_text(encoding="utf-8")) == []


def test_the_parse_keeps_each_field():
    p = cw.parse_text(LESSON6)
    nodes = {n["name"]: n for n in p["nodes"]}
    assert nodes["count_kinds"]["func"] == "counts the lines of each kind"
    assert nodes["LogStore.clear"]["modify"] == [{"target": "[Data: LogStore.stack_a]", "assign": "clear"}]
    stack = next(e for e in p["entities"] if e["name"] == "[Data: LogStore.stack_a]")
    assert (stack["kind"], stack["in"]) == ("Data", "list[str]")
    # `wins` and `(!)` give the order of the writes: the source of finding H-1
    reload = next(s for s in stack["sequence"] if s["event"] == "reload")["steps"]
    assert reload == [{"node": "write_alarms", "wins": False, "early": True},
                      {"node": "LogStore.load", "wins": True, "early": False}]
    assert p["findings"][0]["id"] == "H-1" and p["findings"][0]["anchor"] == "[Data: LogStore.stack_a]"
    assert p["findings"][0]["decision"].startswith("no change to the graph")


def line_of(text, start):
    return next(i for i, l in enumerate(text.splitlines(), 1) if l.startswith(start))


# one break for each kind of line that is not read: (name, the text before, the text after, the start of the line)
BREAKS = [
    ("section", "## Findings", "## Notes\n\nfree text\n\n## Findings", "## Notes"),
    ("node field", "func: counts the lines of each kind", "fucn: counts the lines of each kind", "fucn:"),
    ("entity field", "desc: the log that the tool reads", "desk: the log that the tool reads", "desk:"),
    ("finding field", "effect: the alarm file shows", "efect: the alarm file shows", "efect:"),
    ("gone field", "func: counts the lines of each kind", "func: counts the lines of each kind\ninner: read_lines", "inner:"),
    ("when alone", "## Edges\n\n", "## Edges\n\nwhen: has_alarm.alarm\n", "when: has_alarm.alarm"),
    ("no in and out", "## Entities", "summary_line\nreq: R-7\nfunc: writes one line\n\n## Entities", "summary_line"),
    ("no finding line", "finding H-1 the alarm file", "H-1 the alarm file", "H-1 the alarm file"),
]


@pytest.mark.parametrize("name,before,after,start", BREAKS, ids=[b[0] for b in BREAKS])
def test_each_break_is_a_line_not_read_on_its_line(name, before, after, start):
    assert LESSON6.count(before) == 1
    g = LESSON6.replace(before, after)
    assert [u["line"] for u in cw.unread(g)] == [line_of(g, start)]


def test_a_key_two_times_is_not_read_and_does_not_change_the_contract():
    g = LESSON6.replace("out: bool alarm", "out: bool alarm\nout: int alarm")
    assert [u["line"] for u in cw.unread(g)] == [line_of(g, "out: int alarm")]
    node = next(n for n in cw.parse_text(g)["nodes"] if n["name"] == "has_alarm")
    assert node["out"]["type"] == "bool"


def test_two_examples_lines_are_read():
    # `examples:` (and `oracle:`) are the keys that a node can have more than one time
    g = LESSON6.replace('examples: (T-5) counts "A": `1` → alarm True',
                        'examples: (T-5) counts "A": `1` → alarm True\nexamples: (T-6) counts "B": `2` → alarm False')
    assert cw.unread(g) == []
    assert len(next(n for n in cw.parse_text(g)["nodes"] if n["name"] == "has_alarm")["examples"]) == 2


def test_an_edge_to_a_node_of_another_file_is_read():
    # a node can live in another graph file of the same system; the edge is read, not an error
    g = LESSON6.replace("## Edges\n\n", "## Edges\n\ncount_kinds.counts ──▶ other_graph_node.counts\n")
    assert cw.unread(g) == []


def test_the_lint_fails_on_each_line_that_is_not_read(tmp_path, capsys):
    ok = tmp_path / "ok.md"
    ok.write_text(LESSON6, encoding="utf-8")
    out = tmp_path / "parse.json"
    assert lint.main([str(ok), "--json", str(out)]) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))["nodes"]) == 11
    bad = tmp_path / "bad.md"
    bad.write_text(LESSON6.replace("func: counts", "fucn: counts"), encoding="utf-8")
    capsys.readouterr()
    assert lint.main([str(bad)]) == 1
    assert "not read: `fucn:" in capsys.readouterr().out
    empty = tmp_path / "empty.md"
    empty.write_text("# no graph\n", encoding="utf-8")
    assert lint.main([str(empty)]) == 1


def test_the_lint_summary_starts_with_not_read_and_has_no_findings_count(tmp_path, capsys):
    """`findings=N` counted the entries of `## Findings`; readers took it for lint errors (recorded 13
    times as "lint exit 0"). The line starts with what the lint is about: the lines not read."""
    ok = tmp_path / "ok.md"
    ok.write_text(LESSON6, encoding="utf-8")
    assert lint.main([str(ok)]) == 0
    line = capsys.readouterr().out.splitlines()[-1]
    assert line.startswith("not read=0 ") and "findings=" not in line
