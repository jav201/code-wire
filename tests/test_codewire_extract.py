"""Tests for the Code-Wire extractor (format B, marks, signatures, the real calls).

Why these matter: the link between the graph and the code is only as good as (1) binding a mark to the
def it names, (2) reading the graph text, (3) reporting drift when the code and the contract of a node
disagree (the `Worker` output of A3e3 is such a drift), and (4) listing the real calls between marked
nodes, also through an unmarked helper. In a data-flow audit, that list showed that the verify step
calls the same reader as the load: a shared oracle that no other check saw.
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
    load.values ──▶ check.path
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
    findings, calls = cw.diff(marks, nodes, lifted, top_level)
    return findings, calls, lifted, top_level


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
    assert nodes["Box.__init__"]["in"][1]["type"] == "Optional[str]"  # `X?` (Q27)
    assert nodes["Box.size"]["in"][0]["kind"] == "self" and nodes["Box.size"]["reqs"] == []
    assert nodes["Box.size"]["out"]["names"] == ["n"]  # `{keys}` stripped
    assert nodes["ghost"]["reqs"] is None and nodes["ghost"]["in"][0]["kind"] == "untyped"


def test_edges_parse_when_and_unknown_ends():
    nodes = [n["name"] for n in cw.parse_graph(GRAPH)]
    edges = cw.parse_edges(GRAPH, nodes)
    assert len(edges) == 4
    assert edges[0]["src"]["entity"] == "[I/O: file]" and edges[0]["dst"] == {"entity": None, "field": None, "node": "Box.__init__", "port": "path"}
    assert edges[2]["dst"]["node"] == "check" and edges[2]["dst"]["port"] == "path"
    assert edges[2]["when"] == "limit > 0" and edges[1]["when"] is None
    assert edges[3]["dst"]["unknown"] == "nowhere.x"


def test_deliberate_mismatches_are_reported(tmp_path):
    findings, *_ = _run(tmp_path)
    # load: graph has `dedupe`, `extra` the code lacks; code has `limit`; `mode` default differs;
    # graph returns a tuple, code a list.
    assert _has(findings, "input_missing_in_code", "`dedupe`")
    assert _has(findings, "input_missing_in_code", "`extra`")
    assert _has(findings, "input_missing_in_graph", "`limit: int`")
    assert _has(findings, "default_mismatch", "`mode`")
    assert _has(findings, "output_type_mismatch", "list[int]")
    assert _has(findings, "module_mismatch", "other.py")  # check lives in mod.py
    assert _has(findings, "graph_node_without_mark", "`ghost`")
    # Box.__init__ agrees with the graph, `X?` and `= None` included: no drift against it.
    assert not [f for f in findings if f["where"] == "mod.py:5" and not f["kind"].startswith("info_")]


def test_the_real_calls_are_listed_also_through_an_unmarked_helper(tmp_path):
    findings, calls, lifted, top_level = _run(tmp_path)
    # load -> _helper (unmarked) -> Box(...): lifted to load -> Box.__init__
    assert ("load", "Box.__init__") in lifted
    assert {"caller": "load", "callee": "Box.__init__", "sites": lifted[("load", "Box.__init__")]} in calls
    assert {"caller": "load", "callee": "check", "sites": lifted[("load", "check")]} in calls
    # a call is a fact of the code, not a finding: the graph does not have to declare it
    assert not [f for f in findings if "c15" in f["kind"]]
    # run() has no marked node above -> top level; super().__init__ is not a construction of Box
    assert top_level["load"] and "Box.__init__" not in top_level


def test_type_normalisation_levels():
    assert cw.type_match("List[int]", "list[int]") == "exact"
    assert cw.type_match(cw.graph_type("str?"), "str | None") == "exact"
    assert cw.type_match("dict", "dict[str, Any]") == "loose"
    assert cw.type_match("Optional[list[dict]]", "Optional[list[dict[str, Any]]]") == "loose"
    assert cw.type_match("list[int]", "set[int]") == "mismatch"


def test_mark_naming_a_different_def_is_reported(tmp_path):
    (tmp_path / "m.py").write_text("class A:\n    # node: A.renamed  []\n    def run(self) -> None:\n        pass\n", encoding="utf-8")
    parsed, _ = cw.parse_files(tmp_path)
    findings, _ = cw.diff(cw.extract_marks(parsed), [], {}, {})
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


def test_modify_targets_keep_their_order_and_lose_the_kind():
    # `modify:` names an input of the node (changed in place) or an entity; the recorder keeps the input
    # after the call, and an entity of the own class (A2g)
    nodes, _, _, _ = cw.load_graphs([GRAPH_Q28])
    assert nodes[0]["modify"] == ["mem_map", "document.entries[].status", "[I/O: out]", "ghost_input", "[Data: nowhere]"]
    assert nodes[0]["assign"] == ["replace", "replace", "replace", "append", "clear"]


def test_optional_callable_notation():
    assert cw.graph_type("(->datetime)?") == "Optional[Callable[[], datetime]]"
    assert cw.type_match(cw.graph_type("(->datetime)?"), "Optional[Callable[[], datetime]]") == "exact"
    assert cw.graph_type("A->B?") == "Callable[[A], Optional[B]]"  # `?` after the arrow binds to the result


def test_two_graph_files_merge_and_report_conflicts():
    other = GRAPH_Q28.replace("in: dict[int, int] mem_map;", "in: dict mem_map;")
    nodes, _, entities, conflicts = cw.load_graphs([GRAPH_Q28, GRAPH, other])
    assert {n["name"] for n in nodes} >= {"patch", "load", "Box.__init__"}
    assert conflicts == ["patch"] and "[I/O: out]" in entities and "[I/O: file]" in entities


def test_another_req_in_a_second_graph_file_is_a_conflict():
    # part 60: F1 named requirements and two pilot graphs said `to trace` for the same nodes; the first file
    # won with no word, and the order of the files changed the report. Now it is a conflict.
    other = GRAPH_Q28.replace("req: R-9", "req: to trace")
    _, _, _, conflicts = cw.load_graphs([GRAPH_Q28, other])
    assert conflicts == ["patch"]


def test_out_none_is_a_type_not_a_name():
    # §3.1: `out: None` = the node only modifies; it must match a `-> None` annotation, not read as untyped.
    assert cw.parse_out("None") == {"type": "None", "names": [], "raw": "None"}
    assert cw.type_match(cw.parse_out("None")["type"], "None") == "exact"


def test_optional_marker_converts_at_any_depth():
    # M-5 (first real use): `Sequence[int?]?` stayed half-converted and gave 2 false type mismatches.
    assert cw.graph_type("Sequence[int?]?") == "Optional[Sequence[Optional[int]]]"
    assert cw.type_match(cw.graph_type("Sequence[int?]?"), "Optional[Sequence[Optional[int]]]") == "exact"
    assert cw.graph_type("dict[str, list[int?]]") == "dict[str, list[Optional[int]]]"
    assert cw.graph_type("str?") == "Optional[str]"


CLOSURE = textwrap.dedent('''
    # node: run_flow  []
    def run_flow(spec):
        return spec

    def _chain_inputs(spec):
        return spec

    # node: inputs_of  []
    def inputs_of(spec):
        return spec

    # node: run_set  []
    def run_set(chains, pool, run_one=None):
        execute = run_one if run_one is not None else run_flow

        def _run_one(spec):
            _chain_inputs(spec)
            inputs_of(spec)
            return execute(spec)

        if pool:
            return list(pool.map(_run_one, chains))
        return [_run_one(c) for c in chains]

    # node: unrelated  []
    def unrelated(run_flow):
        return run_flow
''')


def test_c15_lifts_through_a_closure_and_a_function_passed_as_a_value(tmp_path):
    # M-5 (first real use): the calls of `run_chain_set` went through the closure `_run_one`, and
    # `run_flow` was a value. The extractor saw none of them and reported 2 false C15 absences.
    (tmp_path / "m.py").write_text(CLOSURE, encoding="utf-8")
    parsed, _ = cw.parse_files(tmp_path)
    lifted, _, _ = cw.lift_calls(parsed, cw.extract_marks(parsed))
    assert lifted[("run_set", "inputs_of")] == ["m.py:19"]          # a call inside the closure
    assert lifted[("run_set", "run_flow")] == ["m.py:15 (ref)"]     # a value: the site says `ref`
    assert ("unrelated", "run_flow") not in lifted                  # a parameter with the same name is not a ref


def test_a_section_that_is_gone_is_a_line_not_read():
    # `## Boundary` and `## Routes` left the notation (part 64); a graph that still has one hears it
    g = GRAPH + "\n## Boundary\n\n[Outside: key press] ──▶ Box.__init__\n"
    assert [u["text"] for u in cw.unread(g) if u["text"].startswith("section")] == ["section `Boundary`"]


def test_path_keeps_only_the_marks_of_one_slice(tmp_path):
    # M-13: the extractor read the whole repository, and the marks of other batches were findings
    (tmp_path / "mod.py").write_text(CODE, encoding="utf-8")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "x.py").write_text("# node: stray  []\ndef stray() -> None:\n    pass\n", encoding="utf-8")
    g = tmp_path / "g.md"
    g.write_text(GRAPH, encoding="utf-8")
    for extra, want in (([], True), (["--path", "mod.py"], False)):
        out = tmp_path / ("out" + str(len(extra)))
        cw.main(["--repo", str(tmp_path), "--graph", str(g), "--out", str(out), *extra])
        assert ("`stray`" in (out / "diff-report.md").read_text(encoding="utf-8")) is want
