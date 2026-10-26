"""Tests for the script recorder (A2c).

Why these matter: the threads of the two app audits come from probe scripts, not from pytest, and
each thread line names a step (`(U1.3)`). If the recorder only works under pytest, those runs give no
events; if the steps are lost, an example can not be tied to the step that the graph names. A failed
script must still leave its log: a probe that crashes is exactly the run you need to read.
"""
import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"

APP = '''\
class App:
    def action_load(self, text):
        return load(text)


def load(text):
    return parse(text) + "!"


def parse(text):
    return text.upper()
'''

GRAPH = '''\
## Nodes

load
in: str text
out: str loaded
module: app.py

parse
in: str text
out: str parsed
module: app.py
'''

SCRIPT = '''\
import sys
import codewire_events
from app import App, load

sys.__stdout__.write("== U1.0 start\\n")   # how Textual prints for a running app
load("p0")
print("== U1.1 key l")
App().action_load("p1")
codewire_events.step("U1.2")
load("p2")
print("== U1.3 the end")
if "--fail" in sys.argv:
    raise SystemExit(3)
if "--crash" in sys.argv:
    raise RuntimeError("the probe broke")
if "--chdir" in sys.argv:
    import os, tempfile
    os.chdir(tempfile.mkdtemp())   # the app probes do this: each one works in its own temp folder
'''


def project(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "app.py").write_text(APP, encoding="utf-8")
    (tmp_path / "g.md").write_text(GRAPH, encoding="utf-8")
    (tmp_path / "probe.py").write_text(SCRIPT, encoding="utf-8")
    return code


def run(tmp_path, *extra):
    code = project(tmp_path)
    cmd = [sys.executable, str(TOOLS / "cw_record_run.py"), "--graph", str(tmp_path / "g.md"), "--path", str(code),
           "--step-regex", r"^== (U\d+\.\d+)", "--events", str(tmp_path / "ev.jsonl"), "--trace", str(tmp_path / "t.json"),
           str(tmp_path / "probe.py"), *extra]
    env = {"PYTHONPATH": str(TOOLS), "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    elsewhere = tmp_path / "elsewhere"   # the working folder holds no code: the root comes from --path
    elsewhere.mkdir(exist_ok=True)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env, cwd=elsewhere)
    rows = [json.loads(line) for line in (tmp_path / "ev.jsonl").read_text(encoding="utf-8").splitlines()]
    evs = [e for e in rows if "node" in e]
    run.markers = [e["step"] for e in rows if e.get("kind") == "step"]
    return p, sorted(evs, key=lambda e: e["seq"])


def test_a_script_gives_events_with_roots_and_steps(tmp_path):
    p, evs = run(tmp_path)
    assert p.returncode == 0, p.stderr
    got = [(e["step"], e["root"], e["parent"], e["node"], e["out"]) for e in evs]
    assert got == [
        ("U1.0", "harness", "harness", "load", "P0!"),           # a line on sys.__stdout__ set the step
        ("U1.0", "harness", "load", "parse", "P0"),
        ("U1.1", "App.action_load", "ENTRY", "load", "P1!"),     # a printed line set the step
        ("U1.1", "App.action_load", "load", "parse", "P1"),
        ("U1.2", "harness", "harness", "load", "P2!"),           # the script set the step itself
        ("U1.2", "harness", "load", "parse", "P2"),
    ]
    assert {e["run"] for e in evs} == {"probe"}
    # one step marker for each step, also for U1.3, where no node runs (A3b)
    assert run.markers == ["U1.0", "U1.1", "U1.2", "U1.3"]
    # the printed output still reaches the console
    assert "== U1.1 key l" in p.stdout and "== U1.3 the end" in p.stdout


def test_the_trace_view_is_written_too(tmp_path):
    p, evs = run(tmp_path)
    trace = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert [c["in"]["text"] for c in trace["load"]] == ["p0", "p1", "p2"]
    assert trace["_skipped"] == []


def test_a_failed_script_still_leaves_its_log_and_its_exit_code(tmp_path):
    p, evs = run(tmp_path, "--fail")
    assert p.returncode == 3
    assert len(evs) == 6


def test_relative_output_paths_survive_a_chdir_of_the_script(tmp_path):
    code = project(tmp_path)
    cmd = [sys.executable, str(TOOLS / "cw_record_run.py"), "--graph", str(tmp_path / "g.md"), "--path", str(code),
           "--events", "ev.jsonl", "--trace", "t.json", str(tmp_path / "probe.py"), "--chdir"]
    env = {"PYTHONPATH": str(TOOLS), "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env, cwd=tmp_path)
    assert p.returncode == 0, p.stderr
    rows = [json.loads(l) for l in (tmp_path / "ev.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len([r for r in rows if "node" in r]) == 6
    assert (tmp_path / "t.json").exists()


def test_a_crashed_script_still_leaves_its_log(tmp_path):
    p, evs = run(tmp_path, "--crash")
    assert p.returncode != 0 and "the probe broke" in p.stderr
    assert len(evs) == 6
