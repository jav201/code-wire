"""Tests for the coherence check (C2, C3, C4, C7, C10) with the v2.6 syntax.

Why these matter: on a flow slice (app first-use), C2, C3 and C4 reported 36 + 16 + 24 open items,
and the review could not see the real ones among them. The v2.6 syntax (caller edge, `## Boundary`,
`[Outside: …]`, `discarded:`, `when:` with an output) must close the edge of the slice, and the check
must still report a real gap: an output that nothing uses and that no line declares.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_coherence as cc  # noqa: E402

NODES = """## Nodes

OpenFolderChip._open_target
req: LLR-148.1
in: OpenFolderChip self
out: None
func: opens the folder of the chip
module: tui/open_folder_chip.py
modify: [Interface: status line] (replace)
examples: (TC-704, inferred) family "checks"

resolve_chip_target
req: LLR-148.1
in: str family
out: Path? target
func: maps a family to its home
module: tui/services/folder_open_service.py
examples: (TC-704) family "checks" → target ".../proj1/checks"

is_openable_chip_dir
req: LLR-148.8
in: Path target; Path root
out: bool openable
func: true only for a directory inside the root
module: tui/services/folder_open_service.py
examples: (AT-B97-12, synthetic) target ".../flows" → openable False

open_folder_in_file_manager
req: LLR-148.5
in: Path path; str label = "folder"
out: bool opened
func: starts the file manager on the path
module: tui/services/folder_open_service.py
modify: [Interface: status line] (replace)
examples: (TC-705) path "/tmp/some dir" → opened True

## Entities

[Interface: status line]
in: str
desc: the status line of the screen
"""

V25 = NODES + """
## Edges

OpenFolderChip._open_target ──▶ resolve_chip_target.family
OpenFolderChip._open_target ──▶ is_openable_chip_dir.root
resolve_chip_target.target ──▶ is_openable_chip_dir.target
resolve_chip_target.target ──▶ open_folder_in_file_manager.path
when: openable is True
"""

V26 = V25.replace("when: openable is True", "when: is_openable_chip_dir.openable") + """
## Boundary

[Outside: chip press] ──▶ OpenFolderChip._open_target
"""


def test_v25_slice_reports_the_edge_of_the_slice():
    _, res = cc.check([V25])
    assert ("is_openable_chip_dir", "openable") in res["C3"]
    assert "OpenFolderChip._open_target" in res["C4_from"]


def test_v26_syntax_closes_the_edge_of_the_slice_and_keeps_the_real_gap():
    _, res = cc.check([V26])
    assert res["C2"] == []  # the caller edges feed `family` and `root`
    assert res["C4_from"] == [] and res["C4_to"] == []
    # `opened` is not used by the code either: with no `discarded:` line it stays open
    assert res["C3"] == [("open_folder_in_file_manager", "opened")]


def test_discarded_line_with_a_reason_closes_the_output():
    g = V26 + "discarded: open_folder_in_file_manager.opened — the press path shows the status line\n"
    _, res = cc.check([g])
    assert res["C3"] == []


def test_input_with_a_default_is_info_not_an_open_item():
    _, res = cc.check([V26])
    assert ("open_folder_in_file_manager", "label") in res["C2_default"]
    assert ("open_folder_in_file_manager", "label") not in res["C2"]


def test_c2_reports_an_input_that_nothing_feeds():
    _, res = cc.check([V26.replace("OpenFolderChip._open_target ──▶ is_openable_chip_dir.root\n", "")])
    assert res["C2"] == [("is_openable_chip_dir", "root")]


def test_c10_undeclared_target_and_orphan_entity():
    g = V26.replace("modify: [Interface: status line] (replace)\nexamples: (TC-705)",
                    "modify: [I/O: file manager] (append)\nexamples: (TC-705)")
    g = g.replace("[Interface: status line]\nin: str", "[Interface: status line]\nin: str\n\n[Data: unused]\nin: str")
    _, res = cc.check([g])
    assert res["C10_target"] == ["[I/O: file manager]"]
    assert "[Data: unused]" in res["C10_orphan"] and "[Outside: chip press]" not in res["C10_orphan"]


def test_status_tags_the_open_items_for_the_pdr_gate():
    nodes, res = cc.check([V26.replace("OpenFolderChip._open_target ──▶ is_openable_chip_dir.root\n", "")])
    status = {"is_openable_chip_dir": ("NEW", "no def")}
    report = cc.render(res, status)
    assert "`is_openable_chip_dir.root` · NEW" in report
    assert "PDR gate, C2 on the NEW and CHANGED nodes: 1 open." in report


def test_a_call_edge_with_no_ports_does_not_feed_an_input_under_the_text():
    # Metodologia §3.3: a caller edge names the port. A node-to-node line is listed apart, still open.
    g = V26.replace("OpenFolderChip._open_target ──▶ is_openable_chip_dir.root",
                    "OpenFolderChip._open_target ──▶ is_openable_chip_dir")
    _, res = cc.check([g])
    assert res["C2"] == [] and res["C2_call"] == [("is_openable_chip_dir", "root")]
