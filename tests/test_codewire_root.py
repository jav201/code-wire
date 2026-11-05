"""Tests for the project folder before the hash (A2f).

Why these matter: a recording of thread T1 in the worktree `app-wt-i1` and in the main checkout
`app` (the same code) gave other hashes, only because each path of a test file names its checkout.
A diff of two checkouts must stop at a real change, not at the name of the folder. The mask must not hide
too much: a folder whose name only starts with the name of the project is a different folder, and a path
outside the project is a value of the run.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_events as events  # noqa: E402
import cw_record_plugin as rec  # noqa: E402

BASE = Path(r"C:\Users\dev\Github") if os.name == "nt" else Path("/home/dev/github")


@pytest.fixture
def root():
    old = events.ROOT_DIR[0]

    def set_root(path):
        events.ROOT_DIR[0] = os.path.normcase(str(path))
    yield set_root
    events.ROOT_DIR[0] = old


def h(path):
    return events.event_hash("load", {"path": str(path)}, {"FirmwareFile": {"path": str(path)}})


def test_two_checkouts_give_the_same_hash(root):
    root(BASE / "app-wt-i1")
    a = h(BASE / "app-wt-i1" / "examples" / "case_01" / "firmware.s19")
    root(BASE / "app")
    b = h(BASE / "app" / "examples" / "case_01" / "firmware.s19")
    assert a == b


def test_another_file_in_the_project_is_still_a_change(root):
    root(BASE / "app")
    assert h(BASE / "app" / "examples" / "a.s19") != h(BASE / "app" / "examples" / "b.s19")


def test_a_longer_name_is_not_the_project(root):
    # `app` must not mask the start of `app-wt`: that is another folder
    root(BASE / "app")
    inside = h(BASE / "app" / "x.s19")
    sibling = h(BASE / "app-wt" / "x.s19")
    assert inside != sibling
    assert "<ROOT>" not in events.normalize(str(BASE / "app-wt" / "x.s19"))


def test_a_path_outside_the_project_stays(root):
    root(BASE / "app")
    assert h(BASE / "other" / "x.s19") != h(BASE / "another" / "x.s19")


def test_a_drive_is_not_a_project(root):
    root(Path(BASE.anchor))
    text = str(BASE / "app" / "x.s19")
    assert events.normalize(text) == text


def test_the_json_form_of_a_path_is_found_too(root):
    # the hash reads the JSON text, where a backslash of Windows is doubled
    root(BASE / "app")
    assert events.normalize('"' + str(BASE / "app" / "x").replace("\\", "\\\\") + '"') == '"<ROOT>' + (
        "\\\\x" if os.name == "nt" else "/x") + '"'


def test_a_project_in_the_temp_folder_is_root_in_each_run(root):
    a, b = (Path(tempfile.gettempdir()) / n for n in ("cwproj_aaaa", "cwproj_bbbb"))
    root(a)
    ha = h(a / "x.s19")
    root(b)
    assert ha == h(b / "x.s19")


def test_the_event_keeps_the_real_path(root, tmp_path):
    root(tmp_path / "proj")
    events.EVENTS.clear()
    rec.TRACE.clear()
    rec.KEPT.clear()
    load = rec.wrap({"name": "load", "modify": []}, lambda path: len(path))
    real = str(tmp_path / "proj" / "x.s19")
    load(real)
    ev = events.calls_of(events.EVENTS)[-1]
    assert ev["in"]["path"] == real
