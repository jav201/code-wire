"""Tests: the examples of `docs/Notation-Grammar.md` and the parser agree.

Why these matter: the grammar is the definition of the graph text, and the parser is what the tools
really read. A graph can say more than the tools see when the two do not agree. Each example in the
grammar must be read in full: each node, each edge, each `when:` on its edge, each entity, and no line
that the parser does not read. If someone changes the grammar or the parser so that they do not agree,
a test fails.
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
    assert found == set(cw.SECTIONS)


@pytest.mark.parametrize("md", EXAMPLES, ids=[f"example-{i + 1}" for i in range(len(EXAMPLES))])
def test_each_example_is_read_in_full(md):
    nodes, edges, entities, conflicts = cw.load_graphs([md])
    assert not conflicts
    assert cw.unread(md) == []
    # one node for each `req:` line: each node of the grammar has its trace
    assert len(nodes) == len(lines_of(md, "Nodes", lambda l: l.startswith("req:")))
    assert len(edges) == len(lines_of(md, "Edges", lambda l: cw.ARROW in l))
    assert len([e for e in edges if e["when"]]) == len(lines_of(md, "Edges", lambda l: l.startswith("when:")))
    assert set(lines_of(md, "Entities", lambda l: l.startswith("["))) <= set(entities)


def test_an_empty_in_is_a_function_with_no_parameter():
    """`in:` with no value gives no input; `in: None` would give an input with the name `None`."""
    node = cw.parse_graph("## Nodes\n\nLogStore.clear\nreq: R-10\nin:\nout: None\nmodule: logtool/store.py\n")[0]
    assert node["in"] == []


def test_the_parser_knows_each_key_of_the_grammar():
    """A key in the grammar that the parser does not know is lost; a key that only the parser knows is
    not in the notation."""
    keys = re.search(r"^key\s+=(.*?);", DOC, re.S | re.M).group(1)
    assert set(re.findall(r'"(\w+)"', keys)) == set(cw.NODE_KEYS) | {"examples"}
    fkeys = re.search(r"^fkey\s+=(.*?);", DOC, re.S | re.M).group(1)
    assert set(re.findall(r'"(\w+)"', fkeys)) == set(cw.FINDING_KEYS)
    titles = re.search(r"^title\s+=(.*?);", DOC, re.S | re.M).group(1)
    assert set(re.findall(r'"(\w+)"', titles)) == set(cw.SECTIONS)


def test_the_parse_has_the_keys_of_the_json_table():
    """§7 is the contract of `codewire_lint.py --json`: each key of the table, no other."""
    table = dict(re.findall(r"^\| `(\w+)` \| (.*) \|$", cw.section(DOC, "7. What a parse gives"), re.M))
    # the keys of a row: the code words outside the parentheses (the words inside are sub-keys or values)
    want = {k: set(re.findall(r"`(\w+)`", re.sub(r"\([^)]*\)", "", v))) for k, v in table.items()}
    parses = [cw.parse_text(md) for md in EXAMPLES]
    assert all(set(p) == set(table) - {"decl"} for p in parses)
    first = {k: next(p[k][0] for p in parses if p[k]) for k in ("nodes", "entities", "edges", "findings")}
    first["decl"] = first["nodes"]["in"][0]
    first["unread"] = cw.unread("## Notes\n")[0]
    assert {k: set(v) for k, v in first.items()} == want
