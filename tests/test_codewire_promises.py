"""Tests for promises and absence (A3b): `offers:` and `expect none`.

Why these matter: the UI audit found its worst defects where a control promises an action that does not
happen (CW-U-2: after a load, `k Legend` is in the key bar, and the key does nothing) and where nothing
happens at all (CW-U-13: an empty Load gives no feedback). An example line can only say what one run did.
An offer says what every press must do, and `expect none` makes "nothing happened" a checkable claim. A step
in which no node runs must still be in the log, or "nothing ran" and "the step never ran" look the same.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_events as events  # noqa: E402
import codewire_examples as ce  # noqa: E402
import codewire_extract as cw  # noqa: E402
import cw_record_plugin as rec  # noqa: E402

GRAPH = """## Nodes

show_legend
req: R-1
in:
out: None
func: opens the legend
module: app.py

load_file
req: R-2
in: str path
out: None
func: loads a file
module: app.py

## Entities

[Interface: key bar]
desc: the keys under the view
offers: (T, S1) "k Legend" → show_legend
offers: (T, S3) "k Legend" → show_legend
offers: "l Load" → load_file

[Data: App.current_file]
offers: (T, S1) "k Legend" → show_legend

[Interface: help]
offers: k → show_legend
offers: (T, S1) "x Exit" → exit_app
"""


def test_offers_are_read_with_their_source():
    ent = {e["name"]: e for e in cw.parse_text(GRAPH)["entities"]}["[Interface: key bar]"]
    assert ent["offers"][0] == {"source": {"thread": "T", "step": "S1", "root": None},
                                "control": "k Legend", "node": "show_legend"}
    assert ent["offers"][2]["source"] is None


def test_an_offer_of_another_form_is_a_line_not_read():
    # `offers: k → show_legend` has no quotes: the parser skips it, so C16 would check nothing for it
    bad = [u["text"] for u in cw.unread(GRAPH) if "offers" in u["text"]]
    assert len(bad) == 1 and "not of the form" in bad[0]


@pytest.fixture
def log():
    """S1: the key runs show_legend. S2: a load. S3: the key again, but nothing runs (the focus moved: CW-U-2).
    S4: an empty Load: nothing runs at all (CW-U-13)."""
    events.ROOT_DIR[0] = os.path.normcase(str(Path(__file__).resolve().parents[1]))
    events.EVENTS.clear()
    rec.TRACE.clear()
    rec.KEPT.clear()
    show = rec.wrap({"name": "show_legend", "modify": []}, lambda: None)
    load = rec.wrap({"name": "load_file", "modify": []}, lambda path: None)
    events.step("S1")
    show()
    events.step("S2")
    load("fw.s19")
    events.step("S3")
    events.step("S4")
    yield {"T": events.trace_view(events.EVENTS, max_calls=None)}


def node(name, *lines):
    return [{"name": name, "examples": list(lines)}]


def test_expect_none_holds_when_nothing_ran(log):
    assert ce.check(node("load_file", "(T, S4) an empty Load → expect none"), log)[0][2] == "ok"


def test_expect_none_fails_when_the_node_ran(log):
    row = ce.check(node("load_file", "(T, S2) a Load → expect none"), log)[0]
    assert row[2] == "drift" and "S2" in row[3]


def test_expect_none_on_a_step_that_never_ran(log):
    assert ce.check(node("load_file", "(T, S9) → expect none"), log)[0][2] == "step_not_run"


def test_expect_none_needs_a_step_and_an_event_log(log):
    assert ce.check(node("load_file", "(T) → expect none"), log)[0][2] == "not_checkable"
    old = {"T": {k: v for k, v in log["T"].items() if k != "_steps"}}   # a trace has no steps
    assert ce.check(node("load_file", "(T, S4) → expect none"), old)[0][2] == "not_checkable"


def test_a_step_with_no_node_call_is_in_the_log(log):
    assert log["T"]["_steps"] == ["S1", "S2", "S3", "S4"]   # S3 and S4 have no call of a node


def test_an_offer_holds_or_fails_by_its_step(log):
    ents = cw.parse_entity_blocks(GRAPH)
    rows = {(r[0], r[3], r[4]) for r in ce.check_offers([e for e in ents if e["name"] == "[Interface: key bar]"], log)}
    key = "[Interface: key bar]"
    assert (key, "T", "ok") in rows               # S1: the key ran show_legend
    assert (key, "T", "drift") in rows            # S3: the key bar offers k, and nothing ran
    assert (key, "-", "not_checked") in rows      # an offer with no source is not checked


def test_the_report_and_the_exit_code(tmp_path, log):
    graph = GRAPH.replace("func: loads a file\n", "func: loads a file\nexamples: (T, S4) an empty Load → expect none\n")
    (tmp_path / "g.md").write_text(graph, encoding="utf-8")
    path = events.write(tmp_path / "ev.jsonl")
    out = tmp_path / "c16.md"
    assert ce.main(["--graph", str(tmp_path / "g.md"), "--trace", f"T={path}", "--out", str(out)]) == 1
    text = out.read_text(encoding="utf-8")
    assert "## Offers" in text and "the control does not do what it offers" in text
    # read from the file, S4 is still a step of the log: the step markers survive the write and the read
    assert "| `load_file` | T | ok |" in text
