"""Tests for the Code-Wire DDR extractor (format B + C15/O2 lifting).

Why these matter: the DDR loop is only as good as (1) binding a mark to the def it names,
(2) reading the canonical text the methodology actually uses (format B, v2.4), (3) reporting
drift when code and graph disagree, and (4) C15: a call between marked nodes that the graph
does not declare must surface as divergence, even when it goes through an unmarked helper.
A silent pass on (3) or (4) would make the review useless: the pilot's H-1 is exactly such a call.
"""
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_extract as cw  # noqa: E402

CODE = textwrap.dedent('''
    from typing import Callable, Optional

    class Box:
        # node: Box.__init__  [R-1]
        def __init__(self, path: str, endian: Optional[str] = None):
            self.path = path

        # node: Box.size  []
        @property
        def size(self) -> int:
            return 1

    class Child(Box):
        def __init__(self, path: str):
            super().__init__(path)

    def _helper(path):
        return Box(path)

    # node: load  [R-2, R-3]
    def load(path: str, limit: int = 3, mode: str = "fast") -> list[int]:
        _helper(path)
        return [check(path)]

    # node: check  []
    def check(path: str) -> int:
        return 0

    def run():
        load("a")
''')

GRAPH = textwrap.dedent('''
    # Graph

    ## Entities

    [I/O: file]
    in: str
    desc: a file

    ## Nodes

    Box.__init__
    req: R-1
    in: str path; str? endian = None
    out: Box box
    examples: path "a.s19"; endian None → box {path "a.s19"}
    module: mod.py
    examples: path "b.s19"; endian "little" → box {path "b.s19"}

    load
    req: R-2
    in: str path; (Callable) list[int]->list[int] dedupe; dict? extra; str mode = "slow"
    out: tuple(list[int] values, str? note)
    module: mod.py
    inner: check, ghost

    Box.size
    req: to trace
    in: Box self
    out: int n {a, b}
    module: mod.py

    check
    req: to trace
    in: str path
    out: int code
    module: other.py

    ghost
    in: records
    out: dict payload {a, b}
    module: other.py

    ## Edges

    [I/O: file] ──▶ Box.__init__.path
    Box.__init__.box ──▶ Box.size.self
    load.values ──▶ [1→N] check.path
    when: limit > 0
    check.nope ──▶ nowhere.x

    ## Findings

    hallazgo H-1 solape
    in: not a node
''')


def _parsed(tmp_path):
    (tmp_path / "mod.py").write_text(CODE, encoding="utf-8")
    parsed, failed = cw.parse_files(tmp_path)
    assert failed == []
    return parsed


def _run(tmp_path):
    parsed = _parsed(tmp_path)
    marks = cw.extract_marks(parsed)
    nodes = cw.parse_graph(GRAPH)
    edges = cw.parse_edges(GRAPH, [n["name"] for n in nodes])
    lifted, top_level, _ = cw.lift_calls(parsed, marks)
    findings, c15 = cw.diff(marks, nodes, edges, lifted, top_level)
    return findings, c15, lifted, top_level


def _has(findings, kind, text=""):
    return any(f["kind"] == kind and text in f["msg"] for f in findings)


def test_mark_binds_to_following_def_with_qualname_decorator_and_defaults(tmp_path):
    marks = {m["name"]: m for m in cw.extract_marks(_parsed(tmp_path))}
    assert marks["Box.__init__"]["def"]["params"] == [  # self excluded, default kept
        {"name": "path", "type": "str", "default": None},
        {"name": "endian", "type": "Optional[str]", "default": "None"}]
    assert marks["Box.size"]["def"]["qualname"] == "Box.size"  # bound through the decorator
    assert marks["load"]["reqs"] == ["R-2", "R-3"]
    assert marks["load"]["def"]["params"][2] == {"name": "mode", "type": "str", "default": "'fast'"}


def test_format_b_node_parse():
    nodes = {n["name"]: n for n in cw.parse_graph(GRAPH)}
    # entities and hallazgos are not nodes, even when they carry `in:`
    assert set(nodes) == {"Box.__init__", "load", "Box.size", "check", "ghost"}
    load = nodes["load"]
    assert [(p["kind"], p["type"], p["name"], p["default"]) for p in load["in"]] == [
        ("value", "str", "path", None),
        ("callable", "Callable[[list[int]], list[int]]", "dedupe", None),
        ("value", "Optional[dict]", "extra", None),
        ("value", "str", "mode", '"slow"'),
    ]
    assert load["out"] == {"type": "tuple[list[int], Optional[str]]", "names": ["values", "note"],
                           "raw": "tuple(list[int] values, str? note)"}
    assert load["inner"] == ["check", "ghost"]
    assert nodes["Box.__init__"]["in"][1]["type"] == "Optional[str]"  # `X?` (Q27)
    assert nodes["Box.size"]["in"][0]["kind"] == "self" and nodes["Box.size"]["reqs"] == []
    assert nodes["Box.size"]["out"]["names"] == ["n"]  # `{keys}` stripped
    assert nodes["ghost"]["reqs"] is None and nodes["ghost"]["in"][0]["kind"] == "untyped"


def test_edges_parse_when_quantifier_and_unknown_ends():
    nodes = [n["name"] for n in cw.parse_graph(GRAPH)]
    edges = cw.parse_edges(GRAPH, nodes)
    assert len(edges) == 4
    assert edges[0]["src"]["entity"] == "[I/O: file]" and edges[0]["dst"] == {"entity": None, "node": "Box.__init__", "port": "path"}
    assert edges[2]["dst"]["node"] == "check" and edges[2]["dst"]["port"] == "path"  # [1→N] dropped
    assert edges[2]["when"] == "limit > 0" and edges[1]["when"] is None
    assert edges[3]["dst"]["unknown"] == "nowhere.x"


def test_deliberate_mismatches_are_reported(tmp_path):
    findings, *_ = _run(tmp_path)
    # load: mark [R-2, R-3] vs graph R-2; graph has `dedupe`, `extra` the code lacks; code has `limit`;
    # `mode` default differs; graph returns a tuple, code a list.
    assert _has(findings, "req_mismatch", "R-3")
    assert _has(findings, "input_missing_in_code", "`dedupe`")
    assert _has(findings, "input_missing_in_code", "`extra`")
    assert _has(findings, "input_missing_in_graph", "`limit: int`")
    assert _has(findings, "default_mismatch", "`mode`")
    assert _has(findings, "output_type_mismatch", "list[int]")
    assert _has(findings, "module_mismatch", "other.py")  # check lives in mod.py
    assert _has(findings, "graph_node_without_mark", "`ghost`")
    assert _has(findings, "edge_unknown_port", "`nope`")
    assert _has(findings, "edge_unknown_endpoint", "`nowhere.x`")
    # Box.__init__ agrees with the graph, `X?` and `= None` included: no drift against it.
    assert not [f for f in findings if f["where"] == "mod.py:5" and not f["kind"].startswith("info_")]


def test_c15_lifts_through_unmarked_helper_and_flags_undeclared_call(tmp_path):
    findings, c15, lifted, top_level = _run(tmp_path)
    # load -> _helper (unmarked) -> Box(...): lifted to load -> Box.__init__, not declared -> divergence
    assert ("load", "Box.__init__") in lifted
    assert _has(findings, "c15_divergence", "`load` → `Box.__init__`")
    # load -> check is in `inner:` -> converges
    assert {"caller": "load", "callee": "check", "sites": lifted[("load", "check")], "declared_via": "inner"} in c15
    # `ghost` declared in inner but never called -> absence (info, not drift)
    assert _has(findings, "info_c15_absence", "`ghost`")
    # run() has no marked node above -> top level; super().__init__ is not a construction of Box
    assert top_level["load"] and "Box.__init__" not in top_level


def test_c15_edge_counts_as_declaration(tmp_path):
    graph = GRAPH.replace("load.values ──▶ [1→N] check.path", "load.values ──▶ Box.__init__.path")
    graph = graph.replace("inner: check, ghost", "inner: check")
    parsed = _parsed(tmp_path)
    marks = cw.extract_marks(parsed)
    nodes = cw.parse_graph(graph)
    lifted, top, _ = cw.lift_calls(parsed, marks)
    findings, c15 = cw.diff(marks, nodes, cw.parse_edges(graph, [n["name"] for n in nodes]), lifted, top)
    assert not _has(findings, "c15_divergence")
    assert any(c["callee"] == "Box.__init__" and c["declared_via"] == "edge" for c in c15)


def test_type_normalisation_levels():
    assert cw.type_match("List[int]", "list[int]") == "exact"
    assert cw.type_match(cw.graph_type("str?"), "str | None") == "exact"
    assert cw.type_match("dict", "dict[str, Any]") == "loose"
    assert cw.type_match("Optional[list[dict]]", "Optional[list[dict[str, Any]]]") == "loose"
    assert cw.type_match("list[int]", "set[int]") == "mismatch"


def test_mark_naming_a_different_def_is_reported(tmp_path):
    (tmp_path / "m.py").write_text("class A:\n    # node: A.renamed  []\n    def run(self) -> None:\n        pass\n", encoding="utf-8")
    parsed, _ = cw.parse_files(tmp_path)
    findings, _ = cw.diff(cw.extract_marks(parsed), [], [], {}, {})
    assert _has(findings, "mark_name_ne_qualname", "`A.run`")
    assert _has(findings, "mark_without_graph_node")


def test_examples_is_repeatable_and_required(tmp_path):
    # `examples:` is required (§3.1): one line per input → output pair, lines anywhere in the block.
    nodes = {n["name"]: n for n in cw.parse_graph(GRAPH)}
    assert nodes["Box.__init__"]["examples"] == ['path "a.s19"; endian None → box {path "a.s19"}',
                                                  'path "b.s19"; endian "little" → box {path "b.s19"}']
    findings, *_ = _run(tmp_path)
    missing = {f["msg"].split("`")[1] for f in findings if f["kind"] == "graph_examples_missing"}
    assert missing == {"load", "Box.size", "check", "ghost"}


GRAPH_Q28 = textwrap.dedent('''
    ## Entities

    [I/O: out]
    in: str
    desc: written file

    ## Nodes

    patch
    req: R-9
    in: dict[int, int] mem_map; ChangeDocument document; (Callable) (->datetime)? now_fn = None
    out: Summary summary
    func: applies the document to mem_map in place
    modify: mem_map (replace); document.entries[].status (replace); [I/O: out] (replace); ghost_input (append); [Data: nowhere] (clear)
    examples: (T) mem_map {0x10: 0x01}; document (0x10 ← 0xAA) → summary {applied 1}; mem_map[0x10] = 0xAA
    module: mod.py
''')


def test_q28_modify_targets_inputs_or_entities():
    # Q28 (B): `modify:` may name an input of the node (mutated in place) or a declared entity;
    # anything else breaks C10 and must be reported, or a typo in the effect would pass silently.
    nodes, edges, entities, conflicts = cw.load_graphs([GRAPH_Q28])
    assert nodes[0]["modify"] == ["mem_map", "document.entries[].status", "[I/O: out]", "ghost_input", "[Data: nowhere]"]
    findings, _ = cw.diff([], nodes, edges, {}, {}, entities, conflicts)
    bad = sorted(f["msg"].split("`")[1] for f in findings if f["kind"] == "modify_unknown_target")
    assert bad == ["[Data: nowhere]", "ghost_input"]


def test_optional_callable_notation():
    assert cw.graph_type("(->datetime)?") == "Optional[Callable[[], datetime]]"
    assert cw.type_match(cw.graph_type("(->datetime)?"), "Optional[Callable[[], datetime]]") == "exact"
    assert cw.graph_type("A->B?") == "Callable[[A], Optional[B]]"  # `?` after the arrow binds to the result


def test_two_graph_files_merge_and_report_conflicts():
    other = GRAPH_Q28.replace("in: dict[int, int] mem_map;", "in: dict mem_map;")
    nodes, _, entities, conflicts = cw.load_graphs([GRAPH_Q28, GRAPH, other])
    assert {n["name"] for n in nodes} >= {"patch", "load", "Box.__init__"}
    assert conflicts == ["patch"] and "[I/O: out]" in entities and "[I/O: file]" in entities


def test_out_none_is_a_type_not_a_name():
    # §3.1: `out: None` = the node only modifies; it must match a `-> None` annotation, not read as untyped.
    assert cw.parse_out("None") == {"type": "None", "names": [], "raw": "None"}
    assert cw.type_match(cw.parse_out("None")["type"], "None") == "exact"
