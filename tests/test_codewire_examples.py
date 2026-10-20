"""Tests for the examples check and the recorder.

Why these matter: an `examples:` line is only useful if it stays true. The check must (1) flag a
literal value the code no longer produces, (2) not flag the same value written another way
(0x1000 vs 4096, `/` vs `\\` paths, an elided path), (3) skip what the line itself says was not
observed, and (4) see the value a node leaves in an input it modifies (Q28), which is where the
pilot's mistake was. A check that passes on a changed value would make the thread decorative.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_examples as ce  # noqa: E402
import codewire_extract as cw  # noqa: E402
import cw_record_plugin as rec  # noqa: E402

CALL = {"in": {"path": "C:\\tmp\\proj\\prg.s19", "ranges": [[4096, 4100]]},
        "out": {"LoadedFile": {"mem_map": {"0x1000": 1}, "file_type": "s19"}},
        "files": {"C:\\tmp\\proj\\prg.s19": ["S107100001020304DE", "S9030000FC"]}}


def node(name, *lines):
    return {"name": name, "examples": list(lines)}


def test_line_holds_when_values_are_written_another_way():
    line = '(AC-1) path ".../proj/prg.s19", línea 1 `S107100001020304DE` → mem_map {0x1000: 0x01}; ranges [(0x1000, 0x1004)]'
    assert ce.check_line(line, [CALL]) == []


def test_changed_value_is_drift():
    # the graph says 0xAB is loaded; the run has 0x01 -> the thread no longer describes the code
    rows = ce.check([node("load", "(AC-1) path → mem_map {0x1000: 0xAB}")], {"AC-1": {"load": [CALL]}})
    assert rows[0][2] == "drift" and "0xab" in rows[0][3]


def test_changed_text_is_drift():
    rows = ce.check([node("load", '(AC-1) file_type "hex"')], {"AC-1": {"load": [CALL]}})
    assert rows[0][2] == "drift"


def test_thread_tag_is_not_an_anchor_and_unobserved_lines_are_skipped():
    traces = {"AC-1": {"load": [CALL]}}
    rows = ce.check([node("load", "(AC-1, inferred) → 0xFFFF"), node("other", "(AC-1) → 0x1000"),
                     node("load", "(case_03) → 0x1000")], traces)
    assert [r[2] for r in rows] == ["not_observed", "node_not_run", "no_trace"]


def test_best_call_wins():
    other = {"in": {}, "out": {"x": 7}}
    assert ce.check_line("(AC-1) → 0x1000", [other, CALL]) == []


def test_two_graphs_keep_both_threads_of_a_shared_node():
    g = "## Nodes\n\nload\nin: str path\nout: int n\nexamples: ({t}) → 0x1\nmodule: m.py\n"
    nodes, _, _, conflicts = cw.load_graphs([g.format(t="case_03"), g.format(t="AC-1")])
    assert conflicts == [] and nodes[0]["examples"] == ["(case_03) → 0x1", "(AC-1) → 0x1"]


def test_recorder_keeps_the_input_after_the_node_modifies_it():
    # Q28: `modify: mem_map` -> the value the next node receives is the one after the call
    def apply(document, mem_map):
        mem_map[0x1000] = 0xAA
        return {"applied": 1}

    rec.TRACE.clear()
    w = rec.wrap({"name": "apply", "modify": ["mem_map"]}, apply)
    mem = {0x1000: 0x01}
    assert w("doc", mem) == {"applied": 1} and mem == {0x1000: 0xAA}  # behaviour unchanged
    call = rec.TRACE["apply"][0]
    assert call["in"]["mem_map"] == {"0x1000": 1} and call["after"]["mem_map"] == {"0x1000": 170}
    assert ce.check_line("(AC-1) mem_map {0x1000: 0x01} → mem_map[0x1000] pasa a 0xAA", [call]) == []


def test_recorder_caps_calls_and_reads_small_files(tmp_path):
    f = tmp_path / "prg.s19"
    f.write_text("S107100001020304DE\nS9030000FC\n", encoding="utf-8")
    rec.TRACE.clear()
    w = rec.wrap({"name": "load", "modify": []}, lambda path: 4)
    for _ in range(5):
        w(str(f))
    assert len(rec.TRACE["load"]) == rec.MAX_CALLS
    assert rec.TRACE["load"][0]["files"][str(f)][0] == "S107100001020304DE"


def test_address_value_pair_must_match_as_a_pair():
    # the real mutant that survived plain number matching: 0xAB exists in the call, but at 0x80020009
    call = {"out": {"mem_map": {"0x80020008": 0xAA, "0x80020009": 0xAB}}}
    assert ce.check_line("(case_03) mem_map[0x80020008] = 0xAA", [call]) == []
    assert ce.check_line("(case_03) mem_map[0x80020008] = 0xAB", [call]) == ["0x80020008: 0xab"]


def test_a_line_with_no_anchor_is_not_reported_as_ok():
    # M-6 (first-use): 5 of 31 "ok" lines had nothing to compare. An ok must mean "checked and true".
    rows = ce.check([node("load", "(AC-1) the node reads the file and gives its records")], {"AC-1": {"load": [CALL]}})
    assert rows[0][2] == "no_anchor"


def test_short_quoted_text_must_equal_a_whole_recorded_string():
    # M-6: `"ok"` was dropped (shorter than 3 characters), so a wrong status passed. A part of a
    # longer string is not enough: "ok" is inside "token", and that is not the same value.
    assert ce.check_line('(AC-1) → status "ok"', [{"out": {"status": "ok"}}]) == []
    assert ce.check_line('(AC-1) → status "ok"', [{"out": {"status": "token"}}]) == ["ok"]


def test_recorder_skips_a_node_with_no_code_and_lists_it(tmp_path, monkeypatch):
    # M-7 (first-use): in forward, a NEW node has no def yet. The recorder stopped the whole test
    # run, so the agent had to write recording-only copies of each graph.
    (tmp_path / "shipped.py").write_text("def old(x):\n    return x\n", encoding="utf-8")
    graph = tmp_path / "g.md"
    graph.write_text("## Nodes\n\nold\nin: int x\nout: int x\nmodule: shipped.py\n\n"
                     "new_step\nin: int x\nout: int y\nmodule: shipped.py\n\n"
                     "new_file_step\nin: int x\nout: int y\nmodule: not_yet.py\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("CW_GRAPHS", str(graph))
    rec.TRACE.clear()
    rec.pytest_configure(None)
    import shipped
    assert shipped.old(3) == 3 and rec.TRACE["old"][0]["out"] == 3
    assert rec.TRACE["_skipped"] == ["new_step", "new_file_step"]
    rows = ce.check([node("new_step", "(AC-1) x 1 → y 0x2")], {"AC-1": rec.TRACE})
    assert rows[0][2] == "no_def"
