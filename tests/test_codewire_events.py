"""Tests for the event log (A2a).

Why these matter: the app audits found their defects in recorded threads, and the spike of part 41
showed that one example on a node hides what each entry point gives it (`'P1'` from a direct call,
`'Label()'` from the button, `None` from the key). So each recorded call must say (1) which entry point
started it, or that a harness called it directly, (2) which node called it, and (3) a hash that is the
same in every run of the same values, so that two logs can be compared step by step. A recorder that
loses the root, mixes the harness with the app, or hashes a temp folder makes those views wrong.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_events as events  # noqa: E402
import cw_record_plugin as rec  # noqa: E402

REPO = os.path.normcase(str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def clean():
    events.ROOT_DIR[0] = REPO
    events.EVENTS.clear()
    rec.TRACE.clear()
    rec.KEPT.clear()
    yield


def recorded(name, fn):
    return rec.wrap({"name": name, "modify": []}, fn)


class App:
    """An app with entry points (`action_*`, `on_*`) that call graph nodes."""

    def __init__(self, parse, load):
        self.parse, self.load = parse, load

    def action_load(self, text):
        return self.load(text)

    def on_button_pressed(self, text):
        return self.load(text)


def make_nodes():
    parse = recorded("parse", lambda text: text.upper())
    load = recorded("load", lambda text: parse(text) + "!")
    return parse, load


def test_root_is_the_entry_point_and_parent_the_calling_node():
    parse, load = make_nodes()
    App(parse, load).action_load("p1")
    by = {e["node"]: e for e in events.EVENTS}
    assert by["load"]["root"] == "App.action_load" and by["load"]["parent"] == events.ENTRY
    # the inner node keeps the root of the entry point and names the node that called it
    assert by["parse"]["root"] == "App.action_load" and by["parse"]["parent"] == "load"
    assert by["parse"]["in"] == {"text": "p1"} and by["parse"]["out"] == "P1"


def test_a_direct_call_is_the_harness_not_an_entry_point():
    # CW-U-1 hid here: tests called the handler directly, so no run went through the button
    parse, load = make_nodes()
    load("p1")
    assert {e["root"] for e in events.EVENTS} == {events.HARNESS}


def test_each_entry_point_keeps_its_own_examples():
    parse, load = make_nodes()
    app = App(parse, load)
    for text in ("a", "b", "c", "d"):
        app.action_load(text)
        app.on_button_pressed(text)
        load(text)
    roots = [c["root"] for c in rec.TRACE["load"]]
    # three examples for each root, not three for the node: the button is not crowded out by the key
    assert sorted(set(roots)) == ["App.action_load", "App.on_button_pressed", events.HARNESS]
    assert all(roots.count(r) == rec.MAX_CALLS for r in set(roots))
    # the log keeps every call (up to CW_MAX_EVENTS), so the counts of the variants stay true
    assert sum(1 for e in events.EVENTS if e["node"] == "load") == 12


def test_entry_names_outside_the_project_are_not_roots():
    # a framework has its own `on_*` methods (Textual: MessagePump.on_event); only project code counts
    parse, load = make_nodes()
    outside = {}
    exec(compile("def on_event(f, x):\n    return f(x)\n", os.path.join(tempfile.gettempdir(), "framework.py"), "exec"), outside)
    outside["on_event"](load, "p1")
    assert events.EVENTS[-1]["root"] == events.HARNESS


def test_hash_ignores_temp_folders_and_addresses_but_not_values():
    tmp = Path(tempfile.gettempdir())
    a = events.event_hash("copy", {"source": str(tmp / "cwui_ab12" / "fw.s19"), "obj": "<X at 0x0000024E808FC510>"}, "ok")
    b = events.event_hash("copy", {"source": str(tmp / "cwui_zz99" / "fw.s19"), "obj": "<X at 0x0000020419F78750>"}, "ok")
    c = events.event_hash("copy", {"source": str(tmp / "cwui_ab12" / "other.s19"), "obj": "<X at 0x0000024E808FC510>"}, "ok")
    assert a == b       # two runs of the same step: the same hash
    assert a != c       # another file: another hash


def test_extra_volatile_pattern(monkeypatch):
    monkeypatch.setenv("CW_VOLATILE", r'"load_started": [0-9.]+')
    monkeypatch.setattr(events, "VOLATILE", events._volatile())
    assert events.event_hash("n", {"load_started": 1.5}, None) == events.event_hash("n", {"load_started": 9.25}, None)


def test_a_raised_call_is_an_event_and_closes_the_parent():
    boom = recorded("boom", lambda: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        boom()
    after = recorded("after", lambda: 2)
    after()
    assert events.EVENTS[0]["node"] == "boom" and events.EVENTS[0].get("raised") is None  # raised is on the call
    assert events.EVENTS[1]["parent"] == events.HARNESS   # the failed call did not stay open


def test_trace_view_of_the_log_is_the_trace_that_c16_reads():
    parse, load = make_nodes()
    App(parse, load).action_load("p1")
    load("p2")
    view = events.trace_view(events.EVENTS)
    for node in ("parse", "load"):
        assert [(c["root"], c["in"], c["out"]) for c in view[node]] == \
               [(c["root"], c["in"], c["out"]) for c in rec.TRACE[node]]


def test_log_round_trip(tmp_path):
    parse, load = make_nodes()
    events.step("U1.1")
    App(parse, load).action_load("p1")
    path = events.write(tmp_path / "ev.jsonl", skipped=["new_step"])
    back = events.read(path)
    # read() gives the call order (seq); the recorder keeps the order in which the calls returned
    assert [e["hash"] for e in back] == [e["hash"] for e in sorted(events.calls_of(events.EVENTS), key=lambda e: e["seq"])]
    # the step marker is in the file too: a step with no node call is still in the log (A3b)
    assert [m["step"] for m in events.read(path, markers=True) if m.get("kind") == "step"] == ["U1.1"]
    assert [e["node"] for e in back] == ["load", "parse"]
    assert {e["step"] for e in back} == {"U1.1"}
    # the nodes with no code yet travel with the log, so C16 can still tell a NEW node
    assert events.read_meta(path)["skipped"] == ["new_step"]


def dialog_class():
    """A dialog whose handler is itself a graph node."""
    class Screen:
        def on_button_pressed(self, value):
            return value
    Screen.on_button_pressed = rec.wrap({"name": "Screen.on_button_pressed", "modify": []}, Screen.on_button_pressed)
    return Screen


def framework_dispatch(handler, value):
    """Call a handler from code outside the project, as Textual does."""
    outside = {}
    exec(compile("def dispatch(h, v):\n    return h(v)\n", os.path.join(tempfile.gettempdir(), "framework.py"), "exec"), outside)
    return outside["dispatch"](handler, value)


def test_an_entry_node_that_the_framework_calls_is_its_own_root():
    # app smoke run of A2c: `action_load_project` and the dialogs' `on_button_pressed` are nodes, and
    # Textual calls them from its own code. With no rule they were all `harness`.
    framework_dispatch(dialog_class()().on_button_pressed, "P1")
    ev = events.EVENTS[-1]
    assert ev["root"].endswith("Screen.on_button_pressed") and ev["parent"] == events.ENTRY


def test_a_stamp_on_an_argument_gives_the_root_of_the_opener():
    # the adapter stamps a dialog screen when it is pushed; its handler gets the screen as `self`
    dialog = dialog_class()()
    events.stamp(dialog, ("App.action_open", events.ENTRY))
    framework_dispatch(dialog.on_button_pressed, "P1")
    assert events.EVENTS[-1]["root"] == "App.action_open"
