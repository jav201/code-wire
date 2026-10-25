"""Tests: the examples of `docs/Notation-Grammar.md` and the parser agree.

Why these matter: the grammar is the definition of the machine notation, and the parser is what the
tools really read. Before the grammar, the parser skipped each line that it did not know, with no
warning, so a graph could say more than the tools saw. Each example in the grammar must be read in
full: each node, each edge with known ends, each `when:` on its edge, each entity and each
`discarded:` line. If someone changes the grammar or the parser so that they do not agree, a test fails.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import codewire_extract as cw  # noqa: E402

DOC = (ROOT / "docs" / "Notation-Grammar.md").read_text(encoding="utf-8")
EXAMPLES = re.findall(r"^```code-wire\n(.*?)^```", DOC, re.S | re.M)


def lines_of(md, title, pred):
    return [l for l in cw.section(md, title).splitlines() if pred(l)]


def test_the_grammar_has_an_example_for_each_section():
    found = {t for md in EXAMPLES for t in re.findall(r"^## (\w+)", md, re.M)}
    assert found == {"Nodes", "Entities", "Edges", "Boundary", "Routes", "Findings"}


@pytest.mark.parametrize("md", EXAMPLES, ids=[f"example-{i + 1}" for i in range(len(EXAMPLES))])
def test_each_example_is_read_in_full(md):
    nodes, edges, entities, conflicts = cw.load_graphs([md])
    assert not conflicts
    # one node for each `req:` line: each node of the grammar has its trace
    assert len(nodes) == len(lines_of(md, "Nodes", lambda l: l.startswith("req:")))
    arrows = [l for t in ("Edges", "Boundary") for l in lines_of(md, t, lambda l: cw.ARROW in l)]
    assert len(edges) == len(arrows)
    assert not [e["raw"] for e in edges for end in (e["src"], e["dst"]) if "unknown" in end]
    whens = lines_of(md, "Edges", lambda l: l.startswith("when:"))
    assert len([e for e in edges if e["when"]]) == len(whens)
    declared = lines_of(md, "Entities", lambda l: l.startswith("["))
    assert set(declared) <= set(entities)
    assert len(cw.parse_discarded(md)) == len(lines_of(md, "Boundary", lambda l: l.startswith("discarded:")))


def test_empty_in_is_a_function_with_no_parameter():
    """`in:` with no value gives no input; `in: None` gives an input with the name `None` (a false C2)."""
    node = {n["name"]: n for n in cw.load_graphs(EXAMPLES)[0]}["LogStore.clear"]
    assert node["in"] == []


def test_when_names_the_output_first():
    """The tools find the output at the start of the condition (C3 counts it as used)."""
    _, edges, _, _ = cw.load_graphs([md for md in EXAMPLES if "when:" in md])
    assert [e["when"].split()[0] for e in edges if e["when"]] == ["has_alarm.alarm"]


def test_the_parser_knows_each_key_of_the_grammar():
    """A key in the grammar that the parser does not know is lost with no warning; a key that only the
    parser knows is not in the notation."""
    keys = re.search(r"^key\s+=(.*?);", DOC, re.S | re.M).group(1)
    assert set(re.findall(r'"(\w+)"', keys)) == set(cw.NODE_KEYS) | {"examples"}
    fkeys = re.search(r"^fkey\s+=(.*?);", DOC, re.S | re.M).group(1)
    assert {"anchor"} | set(re.findall(r'"(\w+)"', fkeys)) == set(cw.FINDING_KEYS)


@pytest.mark.parametrize("md", EXAMPLES, ids=[f"example-{i + 1}" for i in range(len(EXAMPLES))])
def test_each_example_gives_no_warning(md):
    assert cw.graph_warnings(md) == []


def test_each_warning_code_of_the_grammar_is_given_by_the_parser():
    codes = re.findall(r"^\| (G\d+) \|", DOC, re.M)
    assert codes == [f"G{i}" for i in range(1, 13)]
    assert set(codes) == set(re.findall(r'warn\("(G\d+)"', (ROOT / "tools" / "codewire_extract.py").read_text(encoding="utf-8")))


def test_the_parse_has_the_keys_of_the_json_table():
    """Notation-Grammar.md §8 is the contract of `codewire_lint.py --json`: each key of the table, no other."""
    table = dict(re.findall(r"^\| `(\w+)` \| (.*) \|$", cw.section(DOC, "8. What a parse gives"), re.M))
    # the keys of a row: the code words outside the parentheses (the words inside are sub-keys or values)
    want = {k: set(re.findall(r"`(\w+)`", re.sub(r"\([^)]*\)", "", v))) for k, v in table.items()}
    parses = [cw.parse_text(md) for md in EXAMPLES]
    assert all(set(p) == set(table) - {"decl"} for p in parses)
    first = {k: next(p[k][0] for p in parses if p[k]) for k in ("nodes", "entities", "edges", "discarded", "routes", "findings")}
    first["decl"] = first["nodes"]["in"][0]
    first["warnings"] = cw.graph_warnings("## Notes\n")[0]
    assert {k: set(v) for k, v in first.items()} == want
