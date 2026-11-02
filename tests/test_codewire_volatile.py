"""Tests for volatile values and the oracle of a node (A3c): `volatile:` and `oracle:`.

Why these matter: a diff of two runs must stop at the first real change. In the audited application the load payload
holds `mac_cache_key`, a key made from `id()` of objects, so two equal runs gave other hashes. The
runner of I1c hid it with a regex in `CW_VOLATILE`: the graph did not say it, and a runner that forgets
the regex sees a change that is not there. With `volatile:` the graph says it, and only that value
stops counting: a mask that hides more than the named field would hide a real change too. `oracle:`
gives an outside source a place, because `req:` holds only the ids of the project.
"""
import itertools
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_events as events  # noqa: E402
import codewire_extract as cw  # noqa: E402
import cw_record_plugin as rec  # noqa: E402

GRAPH = """## Nodes

prepare_load
req: R-1
in: str path; float started
out: Prepared payload
func: reads a file into a payload
module: app.py
volatile: started, out.cache_key
oracle: README.md, section "Load"
oracle: the S-record format, srec(5)

timed_count
req: R-2
in: list[str] lines
out: tuple(int count, float took)
func: counts the lines and the time it took
module: app.py
volatile: took

bad_node
req: R-3
in: str path
out: int size
func: a node with wrong fields
module: app.py
volatile: when, out.size
oracle:
"""


class Prepared:
    def __init__(self, rows, cache_key):
        self.rows = rows
        self.cache_key = cache_key


KEYS = itertools.count(140708953516752)   # an address: a new one in each run, as `id()` in the audited application


def node(name):
    return {n["name"]: n for n in cw.load_graphs([GRAPH])[0]}[name]


@pytest.fixture(autouse=True)
def clean():
    events.ROOT_DIR[0] = os.path.normcase(str(Path(__file__).resolve().parents[1]))
    events.EVENTS.clear()
    rec.TRACE.clear()
    rec.KEPT.clear()
    yield


def test_volatile_and_oracle_are_read():
    n = {x["name"]: x for x in cw.parse_text(GRAPH)["nodes"]}["prepare_load"]
    assert n["volatile"] == ["started", "out.cache_key"]
    assert n["oracle"] == ['README.md, section "Load"', "the S-record format, srec(5)"]   # two lines, no G3


def test_a_volatile_item_that_names_nothing_is_a_line_not_read():
    # `volatile: when` names no input and no output: the recorder masks nothing for it, with no word
    bad = [u["text"] for u in cw.unread(GRAPH)]
    assert len(bad) == 1 and "volatile `when`" in bad[0]   # `out.size` is good; two `oracle:` lines are good


def test_volatile_paths_of_a_node():
    assert rec.volatile_paths(node("prepare_load")) == [("in", ["started"]), ("out", ["cache_key"])]
    assert rec.volatile_paths(node("timed_count")) == [("out", [1])]   # the second item of the tuple


def test_mask_changes_only_the_named_item():
    obj = {"Prepared": {"rows": 3, "cache_key": [140708953516752, 0]}}
    assert events.mask(obj, ["cache_key"]) == {"Prepared": {"rows": 3, "cache_key": "<volatile>"}}
    assert events.mask({"a": 1, "b": 2}, ["b"]) == {"a": 1, "b": "<volatile>"}
    assert events.mask([1, 2.5], [1]) == [1, "<volatile>"]
    assert events.mask(obj, ["no_such"]) == obj                # a path that is not there changes nothing


def run_twice(n, fn, first, second):
    w = rec.wrap(n, fn)
    events.step("A")
    w(*first)
    events.step("B")
    w(*second)
    return [e for e in events.calls_of(events.EVENTS)]


def test_a_volatile_field_does_not_change_the_hash():
    fn = lambda path, started: Prepared(3, [next(KEYS), 0])   # noqa: E731  the key of the audited application
    a, b = run_twice(node("prepare_load"), fn, ("fw.s19", 1.5), ("fw.s19", 9.25))
    assert a["hash"] == b["hash"]
    # the event still keeps the values: the hash does not use them, a reader can see them
    assert a["in"]["started"] == 1.5 and b["in"]["started"] == 9.25


def test_a_real_change_still_changes_the_hash():
    rows = iter([3, 4])
    fn = lambda path, started: Prepared(next(rows), [7, 0])    # noqa: E731  the same key, other rows
    a, b = run_twice(node("prepare_load"), fn, ("fw.s19", 1.5), ("fw.s19", 1.5))
    assert a["hash"] != b["hash"]                              # the mask hides only the named field


def test_without_volatile_the_same_runs_differ():
    n = dict(node("prepare_load"), volatile=[])
    fn = lambda path, started: Prepared(3, [next(KEYS), 0])   # noqa: E731
    a, b = run_twice(n, fn, ("fw.s19", 1.5), ("fw.s19", 1.5))
    assert a["hash"] != b["hash"]


def test_an_item_of_a_tuple_output():
    took = iter([0.01, 0.02])
    a, b = run_twice(node("timed_count"), lambda lines: (len(lines), next(took)), (["x"],), (["x"],))
    assert a["hash"] == b["hash"] and a["out"] == [1, 0.01]


def test_diff_of_two_logs_does_not_stop_at_a_volatile_value(tmp_path):
    fn = lambda path, started: Prepared(3, [next(KEYS), 0])   # noqa: E731
    logs = []
    for n in (node("prepare_load"), dict(node("prepare_load"), volatile=[])):
        for _ in range(2):
            events.EVENTS.clear()
            rec.KEPT.clear()
            w = rec.wrap(n, fn)
            events.step("U1.1")
            w("fw.s19", 1.5)
            logs.append(events.read(events.write(tmp_path / f"ev{len(logs)}.jsonl")))
    assert events.diff(logs[0], logs[1]) is None               # with `volatile:`: the same run
    assert events.diff(logs[2], logs[3])["step"] == "U1.1"      # with no `volatile:`: a false change
