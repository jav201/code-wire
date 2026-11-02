"""Tests for the views of the event log and for C16 on a log (A2d).

Why these matter: an early spike showed that the views find what one example per node hides.
`_handle_load_project` got `'Label()'` from the button, `None` from the key and `'P1'` from a direct call:
three examples on one node, one per entry point. The path from the button stopped at that node, and
only the direct call went on to load the project. A view that merges the roots, drops the count of a
path, or a diff that reports a temp folder as a change, would show none of this. C16 must read the log
too, with every call, or a line about the fourth call of a node can not be checked.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_events as events  # noqa: E402
import codewire_examples as ce  # noqa: E402
import cw_record_plugin as rec  # noqa: E402

REPO = os.path.normcase(str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def clean():
    events.ROOT_DIR[0] = REPO
    events.EVENTS.clear()
    rec.TRACE.clear()
    rec.KEPT.clear()
    events.step("-")
    yield


def handle(name):
    return name != "Label()" and name is not None


handle_load_project = rec.wrap({"name": "handle_load_project", "modify": []},
                               lambda name: apply_load(name) if handle(name) else None)
apply_load = rec.wrap({"name": "apply_load", "modify": []}, lambda name: f"loaded {name}")


class App:
    """The three paths of CW-U-1."""

    def on_button_pressed(self):        # the Workspace button: the dialog sends str(Label)
        return handle_load_project("Label()")

    def action_load_project(self):      # key p + enter: the dialog sends nothing
        return handle_load_project(None)


def cw_u1_run(tmp_path=None):
    app = App()
    events.step("U2.4")
    app.on_button_pressed()
    events.step("U2.5")
    app.action_load_project()
    events.step("U2.6")
    handle_load_project("P1")            # the tests call the handler directly
    return sorted(events.calls_of(events.EVENTS), key=lambda e: e["seq"])


def test_examples_are_kept_for_each_root():
    ex = events.examples(cw_u1_run())
    assert [r["in"] for r in ex[("App.on_button_pressed", "handle_load_project")]] == [{"name": "Label()"}]
    assert [r["in"] for r in ex[("App.action_load_project", "handle_load_project")]] == [{"name": None}]
    assert [r["in"] for r in ex[("harness", "handle_load_project")]] == [{"name": "P1"}]
    assert ex[("harness", "handle_load_project")][0]["steps"] == ["U2.6"]


def test_a_path_that_stops_is_a_variant_of_its_own():
    va = events.variants(cw_u1_run())
    assert va["App.on_button_pressed"] == [(("handle_load_project",), 1)]       # it stops: no apply_load
    assert va["harness"] == [(("handle_load_project", "apply_load"), 1)]


def test_variants_count_the_runs_of_a_path():
    app = App()
    for st in ("A", "B", "C"):
        events.step(st)
        app.on_button_pressed()
    events.step("D")
    handle_load_project("P1")
    va = events.variants(sorted(events.EVENTS, key=lambda e: e["seq"]))
    assert va["App.on_button_pressed"] == [(("handle_load_project",), 3)]


def test_matrix_shows_which_root_reached_which_node():
    m = events.matrix(cw_u1_run())
    assert m["harness"] == {"handle_load_project": 1, "apply_load": 1}
    assert "apply_load" not in m["App.on_button_pressed"]          # the cell that shows CW-U-1


def test_diff_finds_the_first_step_that_changed():
    a = cw_u1_run()
    events.EVENTS.clear()
    events.step("U2.4")
    App().on_button_pressed()
    events.step("U2.5")
    App().action_load_project()
    events.step("U2.6")
    handle_load_project("P2")            # another project: the step changes
    b = sorted(events.EVENTS, key=lambda e: e["seq"])
    first = events.diff(a, b)
    assert first["step"] == "U2.6" and first["a"]["in"] == {"name": "P1"} and first["b"]["in"] == {"name": "P2"}
    assert events.diff(a, a) is None


def test_diff_reports_a_call_that_is_missing():
    a = cw_u1_run()
    b = [e for e in a if e["node"] != "apply_load"]   # the fix of a bug, or a new bug: the path is shorter
    first = events.diff(a, b)
    assert first["step"] == "U2.6" and first["b"] is None and first["a"]["node"] == "apply_load"


def test_diff_ignores_volatile_values(tmp_path):
    copy = rec.wrap({"name": "copy", "modify": []}, lambda source: "ok")
    tmp = Path(__import__("tempfile").gettempdir())
    events.step("U1.1")
    copy(str(tmp / "cwui_aaaa" / "fw.s19"))
    a = list(events.EVENTS)
    events.EVENTS.clear()
    copy(str(tmp / "cwui_bbbb" / "fw.s19"))
    assert events.diff(a, list(events.EVENTS)) is None


def test_report_and_cli(tmp_path, capsys):
    cw_u1_run()
    log = events.write(tmp_path / "ev.jsonl")
    text = events.report(events.read(log))
    assert "| `App.on_button_pressed` | `handle_load_project` | `{\"name\": \"Label()\"}`" in text
    assert events.main(["diff", str(log), str(log)]) == 0
    other = tmp_path / "other.jsonl"
    rows = events.read(log)
    rows[-1]["hash"] = "changed"
    events.write(other, rows)
    assert events.main(["diff", str(log), str(other)]) == 1
    assert "differ at step U2.6" in capsys.readouterr().out


def test_c16_reads_every_call_of_a_log(tmp_path):
    # the trace keeps 3 calls per (root, node); a log keeps them all, so a line about call 5 holds
    load = rec.wrap({"name": "load", "modify": []}, lambda n: n * 2)
    for n in range(1, 6):
        load(n)
    log = events.write(tmp_path / "ev.jsonl", skipped=["new_step"])
    graph = tmp_path / "g.md"
    graph.write_text("## Nodes\n\nload\nin: int n\nout: int twice\nexamples: (AC-1) n `5` → `10`\n\n"
                     "new_step\nin: int x\nout: int y\nexamples: (AC-1) x `1` → `2`\n", encoding="utf-8")
    out = tmp_path / "c16.md"
    # `new_step` has no code yet: its line does not hold, so the run is not green
    assert ce.main(["--graph", str(graph), "--trace", f"AC-1={log}", "--out", str(out)]) == 1
    report = out.read_text(encoding="utf-8")
    assert "| `load` | AC-1 | ok |" in report
    assert "| `new_step` | AC-1 | no_def |" in report      # the skipped list came with the log


def test_a_set_has_one_order_in_every_process():
    # A2d smoke run: two equal runs of probe U1 gave other hashes, because the classes of a Textual
    # widget are a set of strings, whose order changes with the hash seed of each process
    import subprocess
    # the second set sits below the depth limit of lit(), where it becomes a repr (A2e smoke run)
    code = ("import sys; sys.path.insert(0, %r); import cw_record_plugin as r; "
            "s = {'modal-confirm', '-active', '-style-default', 'x1', 'y2'}; "
            "print(r.lit(s), r.lit({'a': {'b': {'c': {'d': s}}}}))") % str(Path(rec.__file__).parent)
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={**os.environ, "PYTHONHASHSEED": seed}).stdout for seed in ("1", "2", "3", "4")}
    assert len(outs) == 1 and "modal-confirm" in next(iter(outs))   # one order, and the script ran
