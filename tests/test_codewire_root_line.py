"""Tests for the root of an example line (A3a).

Why these matter: CW-U-1 hid because the tests called the handler directly. A line that says "the button
loads P1" passed C16, because some call of the node had "P1": the direct call of a test, not the button.
With a root on the line, C16 compares only with the calls that the button started, and the same line fails.
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

handle_load_project
req: R-TUI-013
in: str name
out: None
func: loads the project with that name
module: app.py

"""


@pytest.mark.parametrize("line, want", [
    ("(U2, U2.4, root TuiApp.on_button_pressed) path", {"thread": "U2", "step": "U2.4", "root": "TuiApp.on_button_pressed"}),
    ("(T1, t1a) path", {"thread": "T1", "step": "t1a", "root": None}),
    ("(U1.3) path", {"thread": "U1.3", "step": None, "root": None}),
])
def test_the_source_of_an_example(line, want):
    assert cw.example_source(line) == want


class App:
    """The three paths of CW-U-1: the button sends `Label()`, the key sends None, a test sends "P1"."""

    def on_button_pressed(self):
        HANDLE[0]("Label()")

    def action_load_project(self):
        HANDLE[0](None)


HANDLE = [None]


@pytest.fixture
def cw_u1_log():
    events.ROOT_DIR[0] = os.path.normcase(str(Path(__file__).resolve().parents[1]))
    events.EVENTS.clear()
    rec.TRACE.clear()
    rec.KEPT.clear()
    handle = HANDLE[0] = rec.wrap({"name": "handle_load_project", "modify": []}, lambda name: None)
    App().on_button_pressed()
    App().action_load_project()
    handle("P1")
    yield {"U2": events.trace_view(events.EVENTS, max_calls=None)}


def node(*lines):
    return [{"name": "handle_load_project", "examples": list(lines)}]


def test_with_no_root_a_direct_call_hides_the_bug(cw_u1_log):
    rows = ce.check(node('(U2, U2.4) the button loads the project: name "P1"'), cw_u1_log)
    assert rows[0][2] == "ok"        # the call of the test has "P1": the line passes, and the bug hides


def test_with_the_root_the_same_line_fails(cw_u1_log):
    rows = ce.check(node('(U2, U2.4, root App.on_button_pressed) the button loads the project: name "P1"'), cw_u1_log)
    assert rows[0][2] == "drift" and "P1" in rows[0][3]
    rows = ce.check(node('(U2, U2.4, root App.on_button_pressed) name "Label()"'), cw_u1_log)
    assert rows[0][2] == "ok"        # what the button really sends


def test_a_root_that_never_called_the_node(cw_u1_log):
    rows = ce.check(node('(U2, U2.9, root App.action_open_workarea) name "P1"'), cw_u1_log)
    assert rows[0][2] == "root_not_run"


def test_an_old_trace_has_no_root(cw_u1_log):
    old = {"U2": {"handle_load_project": [{k: v for k, v in c.items() if k != "root"}
                                          for c in cw_u1_log["U2"]["handle_load_project"]]}}
    rows = ce.check(node('(U2, U2.4, root App.on_button_pressed) name "Label()"'), old)
    assert rows[0][2] == "root_not_run"   # a line with a root needs an event log
