"""Tests for the Code-Wire extractor (format B, marks, signatures, the real calls).

Why these matter: the link between the graph and the code is only as good as (1) binding a mark to the
def it names, (2) reading the graph text, (3) reporting drift when the code and the contract of a node
disagree (the `Worker` output of A3e3 is such a drift), and (4) listing the real calls between marked
nodes, also through an unmarked helper. In a data-flow audit, that list showed that the verify step
calls the same reader as the load: a shared oracle that no other check saw.
"""
import json
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


# ---------- v3.2: the tools read what authors write ----------

def _module_prefix_repo(tmp_path, code, rel="app/views/home.py"):
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(code, encoding="utf-8")
    return rel


def _node(name, module, typ="int"):
    return f"{name}\nreq: R-1\nin: {typ} n\nout: int r\nmodule: {module}\nexamples: (T) n `1` → `1`\n"


def test_a_module_prefix_on_a_node_name_binds_to_the_def_and_is_not_drift(tmp_path):
    """Seven view modules each have `draw`; node names are unique, so the author writes `home.draw`
    with `module: app/views/home.py`. The tools must read it as the def `draw` of that file."""
    rel = _module_prefix_repo(tmp_path, "# node: home.draw  [R-1]\ndef draw(n: int) -> int:\n    return n\n")
    parsed, _ = cw.parse_files(tmp_path)
    graph = "## Nodes\n\n" + _node("home.draw", rel)
    findings, _ = cw.diff(cw.extract_marks(parsed), cw.parse_graph(graph), {}, {})
    assert findings == []


def test_a_prefix_that_is_not_the_stem_or_a_folder_of_the_module_is_still_drift(tmp_path):
    rel = _module_prefix_repo(tmp_path, "# node: other.draw  [R-1]\ndef draw(n: int) -> int:\n    return n\n")
    parsed, _ = cw.parse_files(tmp_path)
    findings, _ = cw.diff(cw.extract_marks(parsed), cw.parse_graph("## Nodes\n\n" + _node("other.draw", rel)), {}, {})
    assert _has(findings, "mark_name_ne_qualname", "`draw`")


def test_a_parent_folder_name_is_also_a_module_prefix():
    assert cw.drop_module_prefix("lineage.crumbs", "src/app/views/lineage/view.py") == "crumbs"
    assert cw.drop_module_prefix("view.crumbs", "src/app/views/lineage/view.py") == "crumbs"
    assert cw.drop_module_prefix("crumbs", "src/app/views/lineage/view.py") is None


def test_the_marks_tool_writes_the_full_name_above_the_short_def_and_a_real_class_wins(tmp_path, monkeypatch):
    import codewire_marks as cm
    monkeypatch.setattr(cm, "git", lambda *a, **k: "")   # a throwaway folder, not a worktree
    code = ("def draw(n: int) -> int:\n    return n\n\n"
            "class home:\n    def draw(self, n: int) -> int:\n        return n\n")
    rel = _module_prefix_repo(tmp_path, code)
    placed, missing = cm.emit(tmp_path, cw.parse_graph("## Nodes\n\n" + _node("home.draw", rel)))
    text = (tmp_path / rel).read_text(encoding="utf-8").splitlines()
    assert missing == [] and placed[0]["line"] == 5
    assert text[4].strip().startswith("# node: home.draw ") and text[0].startswith("def draw")   # the class method, not the function
    rel2 = _module_prefix_repo(tmp_path, "def draw(n: int) -> int:\n    return n\n", "app/views/home2.py")
    placed, missing = cm.emit(tmp_path, cw.parse_graph("## Nodes\n\n" + _node("home2.draw", rel2)))
    assert missing == [] and (tmp_path / rel2).read_text(encoding="utf-8").splitlines()[0].startswith("# node: home2.draw ")


def test_in_none_means_no_inputs_and_is_not_missing_in_code(tmp_path):
    """8 real findings: "graph input `(none)` not a parameter of `view_lines`"."""
    (tmp_path / "m.py").write_text("# node: view_lines  [R-1]\ndef view_lines() -> list[str]:\n    return []\n", encoding="utf-8")
    parsed, _ = cw.parse_files(tmp_path)
    graph = "## Nodes\n\nview_lines\nreq: R-1\nin: (none)\nout: list[str] lines\nmodule: m.py\nexamples: (T) → `[]`\n"
    findings, _ = cw.diff(cw.extract_marks(parsed), cw.parse_graph(graph), {}, {})
    assert findings == []


LAYER_1 = "## Nodes\n\nview_lines\nreq: R-1\nin: int n\nout: int r\nmodule: m.py\nexamples: (T) n `1` → `1`\n"
LAYER_2 = LAYER_1.replace("in: int n", "in: int n; int width = 80")


def test_layered_graphs_replace_the_earlier_node_and_count_it():
    replaced = []
    nodes, _, _, conflicts = cw.load_graphs([LAYER_1, LAYER_2], layered=True, replaced=replaced)
    assert conflicts == [] and replaced == ["view_lines"]
    assert [p["name"] for p in nodes[0]["in"]] == ["n", "width"]   # the later graph wins


def test_without_layered_two_graphs_that_disagree_are_still_a_conflict():
    replaced = []
    nodes, _, _, conflicts = cw.load_graphs([LAYER_1, LAYER_2], replaced=replaced)
    assert conflicts == ["view_lines"] and replaced == []
    assert [p["name"] for p in nodes[0]["in"]] == ["n"]            # the first wins, as before


def test_layered_flag_on_the_extractor_reports_replaced_nodes_as_info_and_exits_0(tmp_path):
    (tmp_path / "m.py").write_text("# node: view_lines  [R-1]\ndef view_lines(n: int, width: int = 80) -> int:\n    return n\n", encoding="utf-8")
    for i, text in enumerate((LAYER_1, LAYER_2), 1):
        (tmp_path / f"g{i}.md").write_text(text, encoding="utf-8")
    args = ["--repo", str(tmp_path), "--graph", str(tmp_path / "g1.md"), "--graph", str(tmp_path / "g2.md")]
    assert cw.main(args + ["--layered", "--out", str(tmp_path / "a")]) == 0
    report = (tmp_path / "a" / "diff-report.md").read_text(encoding="utf-8")
    assert "1 replaced by a later graph" in report and "Same node with another contract" not in report
    assert cw.main(args + ["--out", str(tmp_path / "b")]) == 1


def test_layered_flag_on_the_marks_tool(tmp_path, capsys, monkeypatch):
    import codewire_marks as cm
    monkeypatch.setattr(cm, "git", lambda *a, **k: "")
    (tmp_path / "m.py").write_text("def view_lines(n: int, width: int = 80) -> int:\n    return n\n", encoding="utf-8")
    for i, text in enumerate((LAYER_1, LAYER_2), 1):
        (tmp_path / f"g{i}.md").write_text(text, encoding="utf-8")
    cm.main(["--repo", str(tmp_path), "--graph", str(tmp_path / "g1.md"), "--graph", str(tmp_path / "g2.md"), "--layered"])
    out = capsys.readouterr().out
    assert "1 marks written" in out and "1 nodes replaced by a later graph: view_lines" in out and "conflicts" not in out


def test_default_mismatch_says_no_default_for_the_side_that_has_none(tmp_path):
    """The graph line had no default and the code had `= None`; the message printed `None` for both."""
    (tmp_path / "m.py").write_text("# node: f  [R-1]\ndef f(x_end: int | None = None) -> int:\n    return 1\n", encoding="utf-8")
    parsed, _ = cw.parse_files(tmp_path)
    graph = "## Nodes\n\nf\nreq: R-1\nin: int? x_end\nout: int r\nmodule: m.py\nexamples: (T) → `1`\n"
    findings, _ = cw.diff(cw.extract_marks(parsed), cw.parse_graph(graph), {}, {})
    msgs = [f["msg"] for f in findings if f["kind"] == "default_mismatch"]
    assert msgs == ["`x_end`: graph no default vs code default `None`"]


def test_default_mismatch_says_no_default_for_the_code_side_too(tmp_path):
    """The mirror case (review F7): the graph has a default, the code has none."""
    (tmp_path / "m.py").write_text("# node: f  [R-1]\ndef f(width: int) -> int:\n    return 1\n", encoding="utf-8")
    parsed, _ = cw.parse_files(tmp_path)
    graph = "## Nodes\n\nf\nreq: R-1\nin: int width = 80\nout: int r\nmodule: m.py\nexamples: (T) → `1`\n"
    findings, _ = cw.diff(cw.extract_marks(parsed), cw.parse_graph(graph), {}, {})
    assert [f["msg"] for f in findings if f["kind"] == "default_mismatch"] == ["`width`: graph default `80` vs code no default"]


def test_none_in_any_case_with_or_without_parentheses_means_no_inputs():
    """Review F8: a Python author writes `(None)` or `none`; each gave an input named so, and a false
    "not a parameter" finding."""
    for value in ("(None)", "none", "None", "(none)"):
        assert cw.parse_graph(f"## Nodes\n\nf\nin: {value}\nout: int r\nmodule: m.py\n")[0]["in"] == []


# ---------- v3.2 fix: a node is its module and its name ----------

def _write(tmp_path, rel, code):
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(code, encoding="utf-8")


def _block(name, module, ins="int n", req="R-1"):
    return f"{name}\nreq: {req}\nin: {ins}\nout: int r\nmodule: {module}\nexamples: (T) n `1` → `1`\n"


def test_one_name_in_two_modules_is_two_nodes_in_one_file_and_with_layered():
    """The real run: `render` in two modules, two functions. The tools kept one and dropped the other."""
    g = "## Nodes\n\n" + _block("draw", "app/views/home.py") + "\n" + _block("draw", "app/views/variants.py", "str s")
    for layered in (False, True):
        replaced = []
        nodes, _, _, conflicts = cw.load_graphs([g], layered, replaced)
        assert conflicts == [] and replaced == []
        assert [(n["module"], n["key"]) for n in nodes] == [
            ("app/views/home.py", "app/views/home.py:draw"), ("app/views/variants.py", "app/views/variants.py:draw")]


def test_layered_does_not_replace_a_node_of_the_same_file():
    """Review F1: with `--layered` a duplicate inside ONE file was swallowed and the run exited 0."""
    g = "## Nodes\n\n" + _block("draw", "app/views/home.py") + "\n" + _block("draw", "app/views/home.py", "str s")
    replaced = []
    nodes, _, _, conflicts = cw.load_graphs([g], layered=True, replaced=replaced)
    assert conflicts == ["draw"] and replaced == [] and len(nodes) == 1
    # with a `draw` in a second module the name is shared, so the conflict names its module
    _, _, _, conflicts = cw.load_graphs([g + "\n" + _block("draw", "app/views/variants.py")], layered=True)
    assert conflicts == ["app/views/home.py:draw"]


def test_a_node_replaced_by_two_later_layers_is_listed_once():
    """Review F6: three layers listed the same node twice."""
    third = LAYER_2.replace("int width = 80", "int width = 100")
    replaced = []
    cw.load_graphs([LAYER_1, LAYER_2, third], layered=True, replaced=replaced)
    assert replaced == ["view_lines"]


REAL_SHAPE_CODE = {
    "app/store/items.py": "# node: render  [R-1]\ndef render(n: int) -> int:\n    return n\n",
    "app/shell/frame.py": "# node: render  [R-2]\ndef render(title: str) -> int:\n    return 1\n",
    "app/views/lines.py": "# node: view_lines  [R-3]\ndef view_lines(n: int, width: int = 80) -> int:\n    return n\n",
}
REAL_SHAPE_G1 = "## Nodes\n\n" + _block("render", "app/store/items.py") + "\n" + _block("view_lines", "app/views/lines.py", req="R-3")
REAL_SHAPE_G2 = ("## Nodes\n\n" + _block("render", "app/shell/frame.py", "str title", req="R-2") + "\n"
                 + _block("view_lines", "app/views/lines.py", "int n; int width = 80", req="R-3"))


def test_the_real_shape_two_graphs_a_name_in_two_modules_and_a_node_changed_later(tmp_path):
    """Two graphs; `render` is two functions in two modules, and `view_lines` is one node that the later
    graph changes. With `--layered` both `render` nodes are checked against their own def, `view_lines`
    is replaced once, and nothing is drift. Without the flag only `view_lines` is a conflict."""
    for rel, code in REAL_SHAPE_CODE.items():
        _write(tmp_path, rel, code)
    (tmp_path / "g1.md").write_text(REAL_SHAPE_G1, encoding="utf-8")
    (tmp_path / "g2.md").write_text(REAL_SHAPE_G2, encoding="utf-8")
    args = ["--repo", str(tmp_path), "--graph", str(tmp_path / "g1.md"), "--graph", str(tmp_path / "g2.md")]
    assert cw.main(args + ["--layered", "--out", str(tmp_path / "a")]) == 0
    data = json.loads((tmp_path / "a" / "extract.json").read_text(encoding="utf-8"))
    assert [f["msg"] for f in data["findings"]] == ["1 replaced by a later graph: `view_lines`"]
    assert sorted((n["module"], n["name"]) for n in data["graph_nodes"]) == [
        ("app/shell/frame.py", "render"), ("app/store/items.py", "render"), ("app/views/lines.py", "view_lines")]
    assert cw.main(args + ["--out", str(tmp_path / "b")]) == 1
    data = json.loads((tmp_path / "b" / "extract.json").read_text(encoding="utf-8"))
    assert [(f["kind"], f["where"]) for f in data["findings"] if f["kind"] == "graph_node_conflict"] == [
        ("graph_node_conflict", "view_lines")]


def test_a_mark_binds_to_the_node_of_its_own_module(tmp_path):
    """Two marks `draw` in two files are not a duplicate: each one is checked against its own node."""
    _write(tmp_path, "app/views/home.py", "# node: draw  [R-1]\ndef draw(n: int) -> int:\n    return n\n")
    _write(tmp_path, "app/views/variants.py", "# node: draw  [R-1]\ndef draw(s: str) -> int:\n    return 1\n")
    parsed, _ = cw.parse_files(tmp_path)
    g = "## Nodes\n\n" + _block("draw", "app/views/variants.py", "str s") + "\n" + _block("draw", "app/views/home.py")
    findings, _ = cw.diff(cw.extract_marks(parsed), cw.load_graphs([g])[0], {}, {})
    assert findings == []


def test_the_calls_name_the_module_when_two_modules_mark_one_name(tmp_path):
    _write(tmp_path, "app/views/home.py",
           "# node: show  [R-1]\ndef show(n: int) -> int:\n    return draw(n)\n\n# node: draw  [R-1]\ndef draw(n: int) -> int:\n    return n\n")
    _write(tmp_path, "app/views/variants.py", "# node: draw  [R-1]\ndef draw(n: int) -> int:\n    return n\n")
    parsed, _ = cw.parse_files(tmp_path)
    lifted, _, _ = cw.lift_calls(parsed, cw.extract_marks(parsed))
    assert list(lifted) == [("show", "app/views/home.py:draw")]


def test_the_marks_tool_puts_one_mark_on_a_def_and_reports_the_second_node(tmp_path, monkeypatch):
    """Review F5: increment 1 names it `draw`, increment 3 renames it `home.draw`; both nodes bound one def,
    two marks were stacked and the extractor said "not directly above a def"."""
    import codewire_marks as cm
    monkeypatch.setattr(cm, "git", lambda *a, **k: "")
    _write(tmp_path, "app/views/home.py", "def draw(n: int) -> int:\n    return n\n")
    g = "## Nodes\n\n" + _block("draw", "app/views/home.py") + "\n" + _block("home.draw", "app/views/home.py")
    placed, missing = cm.emit(tmp_path, cw.load_graphs([g])[0])
    assert [m["name"] for m in placed] == ["draw"]
    assert missing == [{"name": "home.draw", "module": "app/views/home.py", "why": "same def as `draw`"}]
    assert (tmp_path / "app/views/home.py").read_text(encoding="utf-8").count("# node:") == 1


def test_the_marks_tool_marks_one_name_in_two_modules(tmp_path, monkeypatch):
    import codewire_marks as cm
    monkeypatch.setattr(cm, "git", lambda *a, **k: "")
    for rel, code in REAL_SHAPE_CODE.items():
        _write(tmp_path, rel, code.split("\n", 1)[1])   # without the mark line
    nodes = cw.load_graphs([REAL_SHAPE_G1, REAL_SHAPE_G2], layered=True)[0]
    placed, missing = cm.emit(tmp_path, nodes)
    assert missing == [] and sorted((m["file"], m["name"]) for m in placed) == [
        ("app/shell/frame.py", "render"), ("app/store/items.py", "render"), ("app/views/lines.py", "view_lines")]


def test_the_report_names_a_module_only_for_a_name_that_two_modules_share(tmp_path):
    """Operator ruling: a node is written and printed by its bare name; the module appears only for a name
    that two nodes with different `module:` share. With no repeated name, no message names a module; with
    `render` in two modules, the message about `render` names its module and the one about `view_lines` not."""
    for rel, code in REAL_SHAPE_CODE.items():
        _write(tmp_path, rel, code)
    g2_unique = "## Nodes\n\n" + _block("view_lines", "app/views/lines.py", "int n; int width = 1", req="R-3")
    g2_shared = REAL_SHAPE_G2.replace("int n; int width = 80", "int n; int width = 1") + "\n" + _block(
        "render", "app/store/items.py", "int n; int k = 0")
    (tmp_path / "g1.md").write_text(REAL_SHAPE_G1, encoding="utf-8")
    msgs = {}
    for case, g2 in (("unique", g2_unique), ("shared", g2_shared)):
        (tmp_path / f"{case}.md").write_text(g2, encoding="utf-8")
        cw.main(["--repo", str(tmp_path), "--graph", str(tmp_path / "g1.md"), "--graph", str(tmp_path / f"{case}.md"),
                 "--layered", "--out", str(tmp_path / case)])
        data = json.loads((tmp_path / case / "extract.json").read_text(encoding="utf-8"))
        msgs[case] = [f["msg"] for f in data["findings"]]
    assert msgs["unique"] and not [m for m in msgs["unique"] if ".py" in m]
    assert "2 replaced by a later graph: `view_lines`, `app/store/items.py:render`" in msgs["shared"]
    assert not [m for m in msgs["shared"] if ".py" in m and "render" not in m]
