"""Tests for the full parse and the warnings G1–G7 (`codewire_lint.py`, Notation-Grammar.md §8, §9).

Why these matter: before E7b, the parser skipped each line that it did not know, with no warning. A key
with a wrong letter (`fucn:`), a section with a different title or an edge to a node with a wrong name
went out of the graph, and no tool said so. Thus the graph could say more than the tools saw. The three
graphs of the guide are correct graphs: they must give no warning, and the parse must keep each field.
Each broken graph below must give its warning on the correct line.
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
def test_the_guide_graphs_give_no_warning(path):
    assert cw.graph_warnings(path.read_text(encoding="utf-8")) == []


def test_the_parse_keeps_each_field_that_the_parser_skipped_before():
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
    assert [e["quantifier"] for e in p["edges"] if e["quantifier"]] == ["[1→N]"]
    assert p["findings"][0]["id"] == "H-1" and p["findings"][0]["anchor"] == "[Data: LogStore.stack_a]"
    assert p["findings"][0]["decision"].startswith("no change to the graph")


def test_open_and_contract_are_kept():
    g = LESSON6.replace("func: counts the lines of each kind",
                        "func: counts the lines of each kind\nopen: the kinds are not fixed\ncontract: each count is 1 or more")
    node = next(n for n in cw.parse_text(g)["nodes"] if n["name"] == "count_kinds")
    assert (node["open"], node["contract"]) == ("the kinds are not fixed", "each count is 1 or more")


def line_of(text, start):
    return next(i for i, l in enumerate(text.splitlines(), 1) if l.startswith(start))


# one break for each code: (code, the text before, the text after, the start of the line of the warning)
BREAKS = [
    ("G1", "## Findings", "## Notes\n\nfree text\n\n## Findings", "## Notes"),
    ("G2", "func: counts the lines of each kind", "fucn: counts the lines of each kind", "fucn:"),
    ("G2", "desc: the log that the tool reads", "desk: the log that the tool reads", "desk:"),
    ("G2", "effect: the alarm file shows", "efect: the alarm file shows", "efect:"),
    ("G3", "out: bool alarm", "out: bool alarm\nout: bool alarm", "out: bool alarm"),
    ("G4", "count_kinds.counts ──▶ has_alarm.counts", "count_kind.counts ──▶ has_alarm.counts", "count_kind.counts"),
    ("G5", "## Edges\n\n", "## Edges\n\nwhen: has_alarm.alarm\n", "when: has_alarm.alarm\n"),
    ("G6", "anchor: [Data: LogStore.stack_a]", "anchor: LogStore.reload", "anchor: LogStore.reload"),
    ("G6", "anchor: [Data: LogStore.stack_a]", "anchor: [Data: LogStore.stack_b]", "anchor: [Data"),
    ("G7", "## Entities", "summary_line\nreq: R-7\nfunc: writes one line\n\n## Entities", "summary_line"),
    ("G7", "finding H-1 the alarm file", "H-1 the alarm file", "H-1 the alarm file"),
]


@pytest.mark.parametrize("code,before,after,start", BREAKS, ids=[f"{b[0]}-{i}" for i, b in enumerate(BREAKS)])
def test_each_break_gives_its_warning_on_its_line(code, before, after, start):
    assert LESSON6.count(before) == 1
    g = LESSON6.replace(before, after)
    warnings = cw.graph_warnings(g)
    if code == "G3":  # the second of the two lines
        want = [i for i, l in enumerate(g.splitlines(), 1) if l == "out: bool alarm"][1]
    elif code == "G5":
        want = line_of(g, "when: has_alarm.alarm")
    else:
        want = line_of(g, start)
    assert [(w["code"], w["line"]) for w in warnings] == [(code, want)]


def test_two_examples_lines_are_not_a_warning():
    # Notation-Grammar.md §3: `examples:` is the one key that a node can have more than one time.
    # The pilot graphs have nodes with two threads; a G3 there is a false warning.
    g = LESSON6.replace('examples: (T-5) counts "A": `1` → alarm True',
                        'examples: (T-5) counts "A": `1` → alarm True\nexamples: (T-6) counts "B": `2` → alarm False')
    assert cw.graph_warnings(g) == []
    assert len(next(n for n in cw.parse_text(g)["nodes"] if n["name"] == "has_alarm")["examples"]) == 2


def test_a_second_key_line_does_not_change_the_contract():
    g = LESSON6.replace("out: bool alarm", "out: bool alarm\nout: int alarm")
    node = next(n for n in cw.parse_text(g)["nodes"] if n["name"] == "has_alarm")
    assert node["out"]["type"] == "bool"


def test_the_lint_fails_only_when_it_cannot_read_a_block(tmp_path, capsys):
    ok = tmp_path / "ok.md"
    ok.write_text(LESSON6.replace("func: counts", "fucn: counts"), encoding="utf-8")
    out = tmp_path / "parse.json"
    assert lint.main([str(ok), "--json", str(out)]) == 0  # a G2 is a warning
    assert "G2" in capsys.readouterr().out
    assert len(json.loads(out.read_text(encoding="utf-8"))["nodes"]) == 11
    bad = tmp_path / "bad.md"
    bad.write_text(LESSON6.replace("## Entities", "summary_line\nreq: R-7\n\n## Entities"), encoding="utf-8")
    assert lint.main([str(bad)]) == 1
    empty = tmp_path / "empty.md"
    empty.write_text("# no graph\n", encoding="utf-8")
    assert lint.main([str(empty)]) == 1
