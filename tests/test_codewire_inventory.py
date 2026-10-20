"""Tests for the inventory and the generated marks.

Why these matter: the inventory is the draft every flow graph starts from (D2). A domain function
filed as UI would silently drop out of the domain map, and an App method filed as UI would hide
the orchestration where the pilot found H-1 and H-8. The generated marks (D3) must be exactly
what the extractor reads, must never touch code, and must report a node whose def is gone,
because that is what the evolution snapshots watch for.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_extract as cw  # noqa: E402
import codewire_inventory as inv  # noqa: E402
import codewire_marks as mk  # noqa: E402

CORE = '''class FirmwareFile:
    def __init__(self, path: str):
        self.path = path

    def __repr__(self):
        return "FirmwareFile"

    @property
    def size(self) -> int:
        return 0

    def get_overlap_addresses(self) -> list:
        return []


def _helper(x):
    return x
'''
APP = '''from textual.app import App


def _row_state(rec: dict) -> str:
    return "OK"


class TuiApp(App):
    def on_mount(self) -> None:
        pass

    def _compute_mac_view_payload(self) -> dict:
        return {}


class SidePanel(App):
    def refresh_rows(self) -> None:
        pass
'''


def make_repo(tmp_path):
    (tmp_path / "app" / "tui").mkdir(parents=True)
    (tmp_path / "app" / "core.py").write_text(CORE, encoding="utf-8")
    (tmp_path / "app" / "tui" / "app.py").write_text(APP, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text("from app.core import FirmwareFile\nFirmwareFile('x')\n", encoding="utf-8")
    return tmp_path


def kinds(rows):
    return {r["qualname"]: (r["kind"], r["flow"]) for r in rows}


def test_domain_app_and_ui_are_told_apart(tmp_path):
    rows, failed = inv.inventory(make_repo(tmp_path))
    k = kinds(rows)
    assert failed == []
    assert k["FirmwareFile.__init__"] == ("candidate", "F1")  # a constructor is a node (piloto 1)
    assert k["FirmwareFile.get_overlap_addresses"] == ("candidate", "F1")
    assert k["FirmwareFile.__repr__"][0] == "trivial" and k["FirmwareFile.size"][0] == "trivial"
    assert k["_helper"] == ("private", "F1")
    # the App module imports textual, yet its methods and module functions are orchestration, not UI
    assert k["TuiApp._compute_mac_view_payload"] == ("app", None)
    assert k["_row_state"] == ("app", None)
    assert k["TuiApp.on_mount"] == ("handler", None)
    assert k["SidePanel.refresh_rows"] == ("ui", None)


def test_tests_count_names_the_class_for_a_constructor(tmp_path):
    k = {r["qualname"]: r["tests"] for r in inv.inventory(make_repo(tmp_path))[0]}
    assert k["FirmwareFile.__init__"] == 1 and k["FirmwareFile.get_overlap_addresses"] == 0


GRAPH = """## Nodes

FirmwareFile.__init__
req: R-1, R-2
in: str path
out: FirmwareFile app
module: app/core.py

FirmwareFile.get_overlap_addresses
req: to trace
in: FirmwareFile self
out: list overlapped
module: app/core.py

FirmwareFile.gone
req: R-9
in: str x
out: int y
module: app/core.py
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def test_generated_marks_are_what_the_extractor_reads(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "init", "-q")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    nodes = cw.parse_graph(GRAPH)
    placed, missing = mk.emit(repo, nodes)
    assert [m["name"] for m in placed] == ["FirmwareFile.__init__", "FirmwareFile.get_overlap_addresses"]
    assert missing == [{"name": "FirmwareFile.gone", "modulo": "app/core.py", "why": "no def"}]
    marks = cw.extract_marks(cw.parse_files(repo)[0])
    got = {m["name"]: (m["reqs"], m["def"]["qualname"]) for m in marks}
    assert got == {"FirmwareFile.__init__": (["R-1", "R-2"], "FirmwareFile.__init__"),
                   "FirmwareFile.get_overlap_addresses": ([], "FirmwareFile.get_overlap_addresses")}
    # only comment lines were added
    added = [l for l in git(repo, "diff", "-U0").splitlines() if l.startswith("+") and not l.startswith("+++")]
    assert added and all(l[1:].strip().startswith("# node:") for l in added)
    assert not [l for l in git(repo, "diff", "-U0").splitlines() if l.startswith("-") and not l.startswith("---")]


def test_a_second_run_replaces_the_old_marks_and_refuses_real_edits(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "init", "-q")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    nodes = cw.parse_graph(GRAPH)
    mk.emit(repo, nodes)
    mk.emit(repo, nodes)  # regenerated, not duplicated
    assert len(cw.extract_marks(cw.parse_files(repo)[0])) == 2
    core = repo / "app" / "core.py"
    core.write_text(core.read_text(encoding="utf-8") + "\nX = 1\n", encoding="utf-8")
    try:
        mk.emit(repo, nodes)
    except mk.DirtyWorktree:
        pass
    else:
        raise AssertionError("a worktree with edits other than marks must not be touched")
