"""Tests for the state on `self` after a call (A2g).

Why these matter: an app handler often has `out: None`. Its effect is a write to an attribute of the
app, which the graph declares as `modify: [Data: App.attribute]`. Before A2g the recorder kept only the
inputs and the output, so C16 had nothing to compare for such a node, and the lines went to prose (data
MF-5: the declared region that comes back after Load project, CW-D-13, CW-D-14). The recorder must keep
the value of that attribute when the call returns, and only for an entity of the node's own class.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_events as events  # noqa: E402
import codewire_examples as ce  # noqa: E402
import cw_record_plugin as rec  # noqa: E402


class Store:
    def __init__(self):
        self.stack_a = []
        self.view = type("View", (), {"lines": 0})()

    def push_line(self, line):
        if line.startswith("A "):
            self.stack_a.append(line)

    def show(self):
        self.view.lines = len(self.stack_a)


def node(name, *modify):
    return {"name": name, "modify": list(modify), "in": [], "out": {"names": []}}


@pytest.fixture(autouse=True)
def clean():
    events.ROOT_DIR[0] = os.path.normcase(str(Path(__file__).resolve().parents[1]))
    events.EVENTS.clear()
    rec.TRACE.clear()
    rec.KEPT.clear()
    events.step("S1")
    yield


def last():
    return events.calls_of(events.EVENTS)[-1]


def test_the_entity_of_the_own_class_is_kept_after_the_call():
    push = rec.wrap(node("Store.push_line", "[Data: Store.stack_a]"), Store.push_line)
    s = Store()
    push(s, "A 10:02 disk full")
    assert last()["after"] == {"[Data: Store.stack_a]": ["A 10:02 disk full"]}   # the value after the call


def test_an_entity_of_another_class_or_a_function_gives_nothing():
    assert rec.self_entities(node("Store.push_line", "[Data: App.current_file]")) == []
    assert rec.self_entities(node("push_line", "[Data: Store.stack_a]")) == []        # a function
    assert rec.self_entities(node("Store.push_line", "[I/O: alarm file]")) == []      # not [Data]


def test_a_dotted_attribute_and_a_missing_one():
    show = rec.wrap(node("Store.show", "[Data: Store.view.lines]", "[Data: Store.no_such]"), Store.show)
    s = Store()
    s.stack_a = ["A 1", "A 2"]
    show(s)
    assert last()["after"] == {"[Data: Store.view.lines]": 2}   # the missing attribute is not there, and no error


def test_the_state_counts_in_the_hash():
    push = rec.wrap(node("Store.push_line", "[Data: Store.stack_a]"), Store.push_line)
    a, b = Store(), Store()
    b.stack_a = ["A 09:00 old"]
    push(a, "B 10:01 user login")
    push(b, "B 10:01 user login")
    h = [e["hash"] for e in events.calls_of(events.EVENTS)]
    assert h[0] != h[1]   # the same inputs, another state after the call


def test_c16_checks_a_handler_with_no_output():
    push = rec.wrap(node("Store.push_line", "[Data: Store.stack_a]"), Store.push_line)
    s = Store()
    s.stack_a = ["A 09:00 old"]   # this value is only in the state after the call, not in an input
    push(s, "A 10:02 disk full")
    traces = {"T": events.trace_view(events.EVENTS, max_calls=None)}
    ok = ce.check([{"name": "Store.push_line", "examples": [
        '(T, S1) line "A 10:02 disk full" → None; [Data: Store.stack_a] has "A 09:00 old" (1 of 2)']}], traces)
    bad = ce.check([{"name": "Store.push_line", "examples": [
        '(T, S1) line "A 10:02 disk full" → None; [Data: Store.stack_a] has "A 11:00 fan stop"']}], traces)
    assert ok[0][2] == "ok" and bad[0][2] == "drift"
