"""Tests for field edges (A3d): `[Data: X].field ──▶ node` and `node ──▶ [Data: X].field`.

Why these matter: CW-D-7 (a split of a MAC-only session writes a placeholder byte as data) came from
asking which field each reader takes from one entity. The plan reads `ranges`, the writer reads
`mem_map`: two sources of truth in one entity. An edge that names only the entity hides that. Before
A3d the parser read `[Data: X].ranges` as an entity of its own, so the checks of the entity did not see
the edge: C4 said that the reader had no source. The field must stay apart from the entity name.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_extract as cw  # noqa: E402

GRAPH = """## Nodes

load_file
req: R-1
in: str path
out: None
func: loads a file into the app
modify: [Data: App.current_file] (replace)
module: app.py

plan_split
req: R-2
in:
out: int packed
func: plans the files of a split from the ranges
module: app.py

write_split
req: R-3
in:
out: None
func: writes the files of a split from the memory map
modify: [I/O: split files] (replace)
module: app.py

## Entities

[Data: App.current_file]
desc: the loaded file

[Data: App.focused]
desc: the widget that has the focus

## Edges

[Data: App.current_file].ranges ──▶ plan_split
[Data: App.current_file].mem_map ──▶ write_split
[Data: App.focused].widget ──▶ plan_split
plan_split.packed ──▶ [I/O: split files]

## Findings

finding CW-D-7 the split writes a placeholder byte
anchor: [Data: App.current_file].mem_map
"""


def edges():
    return cw.parse_text(GRAPH)["edges"]


def test_the_field_is_kept_apart_from_the_entity():
    src = edges()[0]["src"]
    assert src == {"node": None, "port": None, "entity": "[Data: App.current_file]", "field": "ranges"}
    assert edges()[3]["dst"]["field"] is None      # an edge with no field


def test_a_field_edge_gives_no_warning_and_a_bad_field_gives_g12():
    assert cw.graph_warnings(GRAPH) == []          # also the finding anchor with a field (G6)
    bad = GRAPH.replace("[Data: App.focused].widget ──▶", "[Data: App.focused] widget ──▶")
    bad = bad.replace("].mem_map ──▶", "].1map ──▶")
    w = [(x["code"], x["text"]) for x in cw.graph_warnings(bad)]
    assert [c for c, _ in w] == ["G12", "G12"]
    assert any("`widget` is not" in t for _, t in w) and any("`.1map` is not" in t for _, t in w)
