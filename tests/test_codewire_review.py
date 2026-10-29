"""Tests for the gates of the review by modules (`codewire_review.py`, docs/Review-Method.md).

Why these matter: in the first review by modules (app-b, 2026-10-26) every step was skipped once — a brief
written by hand made the map agents run the test suite, a trace file was left older than a map that landed
after it, three test reviewers got stale cross nodes, and the review of rows whose code sat in another
module bounced between groups. Each gate below must refuse that state and accept the good one, and each
refusal must come from the check that names it, not from an accident of the fixture.
"""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_review as cr  # noqa: E402

CANON = """# Requirements

## G1 — Alpha

| Id | Statement | Status |
|---|---|---|
| R-1 | f doubles its input | active |
| R-2 | C.m does nothing | active |

## G2 — Beta

| Id | Statement | Status |
|---|---|---|
| R-3 | g gives 3 | active |
"""

GRAPH_G1 = """## Nodes

f
req: R-1
in: int x
out: int y
func: doubles x
module: pkg/a.py
examples: (tests/test_a.py::test_f) f(1) is 2

C.m
req: R-2, R-3
in:
out: None
func: does nothing
module: pkg/a.py
examples: (untested) no test found by reading

h
req: R-1
in:
out: int n
func: gives 1
module: pkg/a.py
examples: (untested) no test found by reading

h
req: R-2
in:
out: int n
func: gives 2
module: pkg/c.py
examples: (untested) no test found by reading
"""

GRAPH_G2 = """## Nodes

g
req: R-3
in:
out: int n
func: gives 3
module: pkg/b.py
examples: (untested) no test found by reading
"""


@pytest.fixture
def work(tmp_path):
    base = tmp_path / "base"
    (base / "pkg").mkdir(parents=True)
    (base / "tests").mkdir()
    (base / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (base / "pkg" / "a.py").write_text(
        "def f(x: int) -> int:\n    return x * 2\n\n\nclass C:\n    def m(self) -> None:\n        pass\n\n\n"
        "def h() -> int:\n    def inner():\n        return 0\n    return 1\n", encoding="utf-8")
    (base / "pkg" / "b.py").write_text("def g() -> int:\n    return 3\n", encoding="utf-8")
    (base / "pkg" / "c.py").write_text("def h() -> int:\n    return 2\n", encoding="utf-8")
    (base / "tests" / "test_a.py").write_text("from pkg.a import f\n\n\ndef test_f():\n    assert f(1) == 2\n", encoding="utf-8")
    (base / "REQUIREMENTS.md").write_text(CANON, encoding="utf-8")
    (tmp_path / "groups.csv").write_text("id,group\nR-1,G1\nR-2,G1\nR-3,G2\n", encoding="utf-8")
    (tmp_path / "files.csv").write_text("file,group\npkg/a.py,G1\npkg/c.py,G1\npkg/b.py,G2\n", encoding="utf-8")
    return tmp_path


def run(work, *args):
    return cr.main(["--work", str(work), *args])


def mapped(work, g, graph):
    assert run(work, "brief", "--kind", "map", "--group", g) == 0
    (work / g / "_map").mkdir(exist_ok=True)
    (work / g / "_map" / f"graph-{g}.md").write_text(graph, encoding="utf-8")


def test_the_map_brief_comes_from_the_template_and_makes_the_copy(work):
    assert run(work, "brief", "--kind", "map", "--group", "G1") == 0
    brief = (work / "briefs" / "map-G1.md").read_text(encoding="utf-8")
    assert (work / "G1" / "pkg" / "a.py").exists()
    assert "G1 — Alpha" in brief and "pkg/a.py, pkg/c.py" in brief
    assert "Do not run the test suite" in brief      # the rule the hand-written brief lacked


def test_a_good_map_passes_and_writes_traces(work, capsys):
    mapped(work, "G1", GRAPH_G1)
    assert run(work, "map-gate", "--group", "G1") == 0
    traces = (work / "G1" / "_map" / "TRACES.md").read_text(encoding="utf-8")
    assert "Active rows of the chapter: 2; with a node here: 2" in traces
    assert "review it there" not in traces            # the chapter owns its rows


BREAKS = [
    ("no node", lambda g: g.replace("f\nreq: R-1", "fx\nreq: R-1"), "no node for pkg/a.py::f"),
    ("same name, other module", lambda g: g.split("\nh\nreq: R-2")[0], "no node for pkg/c.py::h"),
    ("unknown requirement", lambda g: g.replace("req: R-1\nin: int x", "req: R-9\nin: int x"), "R-9 does not exist"),
    ("test that does not exist", lambda g: g.replace("test_a.py::test_f", "test_a.py::test_g"), "test_g does not exist"),
    ("line not read", lambda g: g.replace("func: doubles x", "fucn: doubles x"), "not read"),
]


@pytest.mark.parametrize("name,brk,msg", BREAKS, ids=[b[0] for b in BREAKS])
def test_each_map_break_fails_the_gate_with_its_reason(work, capsys, name, brk, msg):
    mapped(work, "G1", brk(GRAPH_G1))
    assert run(work, "map-gate", "--group", "G1") == 1
    assert msg in capsys.readouterr().out
    assert not (work / "G1" / "_map" / "MAP-GATE.ok").exists()


def test_a_code_change_outside_the_map_fails_but_a_node_mark_does_not(work, capsys):
    mapped(work, "G1", GRAPH_G1)
    a = work / "G1" / "pkg" / "a.py"
    a.write_text("# node: f  [R-1]\n" + a.read_text(encoding="utf-8"), encoding="utf-8")
    assert run(work, "map-gate", "--group", "G1") == 0
    a.write_text(a.read_text(encoding="utf-8").replace("x * 2", "x * 3"), encoding="utf-8")
    assert run(work, "map-gate", "--group", "G1") == 1
    assert "changed outside _map/: pkg/a.py" in capsys.readouterr().out


def test_reviewer_briefs_wait_for_the_map_gate(work, capsys):
    mapped(work, "G1", GRAPH_G1)
    assert run(work, "brief", "--kind", "code", "--group", "G1") == 1
    assert "has not passed map-gate" in capsys.readouterr().out
    assert run(work, "map-gate", "--group", "G1") == 0
    assert run(work, "brief", "--kind", "code", "--group", "G1") == 0
    assert run(work, "brief", "--kind", "tests", "--group", "G1") == 0
    assert (work / "G1-tests" / "_map" / "TRACES.md").exists()


def test_cross_nodes_hold_only_the_pertinent_nodes_and_follow_every_landed_map(work):
    mapped(work, "G2", GRAPH_G2)
    assert run(work, "map-gate", "--group", "G2") == 0
    cross = (work / "G2" / "_map" / "cross-nodes.md").read_text(encoding="utf-8")
    assert "C.m" not in cross                          # G1 has not landed yet
    mapped(work, "G1", GRAPH_G1)
    assert run(work, "map-gate", "--group", "G1") == 0
    cross = (work / "G2" / "_map" / "cross-nodes.md").read_text(encoding="utf-8")
    assert "C.m" in cross and "\nf\n" not in cross     # C.m carries R-3; f does not
    assert "R-3" not in (work / "G2" / "_map" / "TRACES.md").read_text(encoding="utf-8").split("no node in any")[1]


def test_a_map_edited_after_the_gate_makes_the_traces_stale(work, capsys):
    mapped(work, "G1", GRAPH_G1)
    assert run(work, "map-gate", "--group", "G1") == 0
    graph = work / "G1" / "_map" / "graph-G1.md"
    later = time.time() + 5
    os.utime(graph, (later, later))
    assert run(work, "brief", "--kind", "code", "--group", "G1") == 1
    assert "older than a passed map" in capsys.readouterr().out


def code_review(work, g, body):
    t = work / g / "_review" / "code" / "tests"
    t.mkdir(parents=True, exist_ok=True)
    (t / "test_review.py").write_text("from pkg.a import f\n\n\ndef test_defect():\n    " + body + "\n", encoding="utf-8")


def test_the_review_gate_needs_a_red_test_and_unchanged_code(work, capsys):
    mapped(work, "G1", GRAPH_G1)
    assert run(work, "map-gate", "--group", "G1") == 0
    assert run(work, "brief", "--kind", "tests", "--group", "G1") == 0
    code_review(work, "G1", "assert f(1) == 2")
    assert run(work, "review-gate", "--group", "G1") == 1
    assert "no code-review test fails" in capsys.readouterr().out
    code_review(work, "G1", "assert f(2) == 5")
    assert run(work, "review-gate", "--group", "G1") == 0
    b = work / "G1-tests" / "pkg" / "b.py"
    b.write_text("def g() -> int:\n    return 4\n", encoding="utf-8")      # a mutant left behind
    assert run(work, "review-gate", "--group", "G1") == 1
    assert "G1-tests: product file changed: pkg/b.py" in capsys.readouterr().out


def test_cohesion_waits_for_every_review_gate(work, capsys):
    for g, graph in (("G1", GRAPH_G1), ("G2", GRAPH_G2)):
        mapped(work, g, graph)
        assert run(work, "map-gate", "--group", g) == 0
    code_review(work, "G1", "assert f(2) == 5")
    assert run(work, "review-gate", "--group", "G1") == 0
    assert run(work, "brief", "--kind", "cohesion") == 1
    assert "review-gate not passed for: G2" in capsys.readouterr().out


def test_note_blocks_are_not_nodes(work):
    # C2 (G8a): a map with `### <file>` headings between nodes made the traces count 7 extra `to trace` nodes
    mapped(work, "G1", GRAPH_G1.replace("## Nodes\n\n", "## Nodes\n\n### pkg/a.py\n\n> the alpha module\n\n"))
    assert run(work, "map-gate", "--group", "G1") == 0
    traces = (work / "G1" / "_map" / "TRACES.md").read_text(encoding="utf-8")
    assert "Nodes: 4; `to trace`: 0" in traces


def test_a_red_test_that_fails_for_its_environment_does_not_pass_the_gate(work, capsys):
    # C2 (G8b): async tests run without their plugin fail as "not natively supported"; the gate must not count that as RED
    mapped(work, "G1", GRAPH_G1)
    assert run(work, "map-gate", "--group", "G1") == 0
    t = work / "G1" / "_review" / "code" / "tests"
    t.mkdir(parents=True)
    (t / "test_review.py").write_text("async def test_defect():\n    assert False\n", encoding="utf-8")
    assert run(work, "review-gate", "--group", "G1") == 1
    assert "fail for their environment" in capsys.readouterr().out
    shim = work / "G1" / "_review" / "shim.py"
    shim.write_text("import asyncio, inspect, pytest\n\n@pytest.hookimpl(tryfirst=True)\ndef pytest_pyfunc_call(pyfuncitem):\n"
                    "    if inspect.iscoroutinefunction(pyfuncitem.obj):\n        asyncio.run(pyfuncitem.obj())\n        return True\n",
                    encoding="utf-8")
    assert run(work, "review-gate", "--group", "G1", "--pytest-arg=-p", "--pytest-arg=shim", "--pythonpath", "_review") == 0


def test_a_map_that_lands_later_refreshes_the_test_reviewers_copy_too(work):
    # C2: G8a-tests was copied before G8b's map landed and kept TRACES that listed G8a only
    mapped(work, "G1", GRAPH_G1)
    assert run(work, "map-gate", "--group", "G1") == 0
    assert run(work, "brief", "--kind", "tests", "--group", "G1") == 0
    mapped(work, "G2", GRAPH_G2)
    assert run(work, "map-gate", "--group", "G2") == 0
    traces = (work / "G1-tests" / "_map" / "TRACES.md").read_text(encoding="utf-8")
    assert "Maps included: G1, G2" in traces
