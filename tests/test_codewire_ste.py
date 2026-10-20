"""Tests for the language check (C17, Language-STE.md).

Why these matter: the project moves to English so that each contract has one meaning. The check is
the oracle for every translated page; if it lets a long or chained sentence through, the translation
looks done and is not. It must also stay quiet on code, tables and literals, or nobody will run it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_ste as ste  # noqa: E402

RULES = Path(__file__).resolve().parents[1] / "docs" / "Language-STE.md"
GLOSSARY = {"touch": "change", "function box": "node"}


def rules(text):
    return [f[2] for f in ste.check_text(text, GLOSSARY)]


def test_length_limit_is_stricter_for_a_numbered_step():
    words21 = " ".join(["word"] * 21) + "."
    assert rules(words21) == []                 # descriptive: 25 is the limit
    assert rules("1. " + words21) == ["S1"]     # step: 20 is the limit
    assert rules(" ".join(["word"] * 26) + ".") == ["S1"]


def test_a_step_gives_one_instruction():
    assert rules("1. Open the file, then run the check.") == ["S2"]
    assert rules("1. Open the file; run the check.") == ["S2"]
    assert rules("1. Open the file.\n2. Run the check.") == []
    assert rules("The tool opens the file; it then reads it.") == []  # not a step: S2 does not apply


def test_paragraph_has_six_sentences_or_fewer():
    assert rules(" ".join(["It runs."] * 6)) == []
    assert rules(" ".join(["It runs."] * 7)) == ["S3"]


def test_glossary_words_and_phrases_are_found_but_not_inside_code():
    assert rules("Do not touch the file.") == ["S4"]
    assert rules("Each function box has one mark.") == ["S4"]
    assert rules("Run `git touch` on the file.") == []


def test_code_tables_headings_and_literals_are_not_prose():
    long = " ".join(["word"] * 40)
    text = f"# {long}\n\n| {long} |\n\n```\n{long}\n```\n\nA literal `{long}` is one word."
    assert rules(text) == []


def test_abbreviations_and_numbers_do_not_split_a_sentence():
    found = ste.sentences("See §3.4, e.g. the node. It runs.")
    assert len(found) == 2
    assert found[0] == "See §3.4, e.g. the node."  # the messages quote the text as it is written


def test_passive_voice_is_a_warning_not_an_error():
    found = ste.check_text("The marks are removed by the tool.", GLOSSARY)
    assert [(f[2], f[3]) for f in found] == [("W1", "warning")]


def test_the_rules_document_reads_its_own_glossary_and_passes_its_own_check():
    glossary = ste.load_glossary(RULES)
    assert glossary["touch"] == "change" and glossary["function box"] == "node"
    assert "thread" not in glossary  # a row with no "Not" only defines the word
    errors = [f for f in ste.check_text(RULES.read_text(encoding="utf-8"), glossary) if f[3] == "error"]
    assert errors == []


GRAPH = """# A graph

## Nodes

Read file
req: R-2
in: str filePath; """ + "; ".join(f"str input{i}" for i in range(30)) + """
out: iter[str] fileLine
func: opens the file and gives it line by line
module: logtool/reader.py
examples: (synthetic) """ + " ".join(["word"] * 30) + """
open: does the node also read a gzip file

## Edges

Validate filePath.validFilePath ──▶ Read file.filePath

## Findings

H-1
anchor: Read file
what: """ + " ".join(["word"] * 26) + """.
evidence: `reader.py:12`; """ + " ".join(["word"] * 30) + """

## Notes

""" + " ".join(["word"] * 26) + "."


def test_a_graph_section_checks_only_its_prose_fields():
    # Language-STE.md §2: the structured lines of a graph are not prose. Without this scope, the
    # model graph itself fails C17 and every real graph gives tens of false errors (M-2, first-use: 95).
    found = ste.check_text(GRAPH, GLOSSARY)
    lines = GRAPH.splitlines()
    flagged = sorted((lines[f[1] - 1].split(":")[0] if ":" in lines[f[1] - 1] else "prose", f[2]) for f in found)
    assert flagged == [("prose", "S1"), ("what", "S1")]  # the long `in:`, `examples:` and `evidence:` lines pass


def test_a_prose_field_in_a_graph_is_still_checked_for_the_glossary():
    assert rules("## Nodes\n\nRead file\nfunc: does not touch the file\nin: str touch") == ["S4"]


def test_the_model_graph_of_the_repository_passes_c17():
    graph = Path(__file__).resolve().parents[1] / "examples" / "logtool-graph.md"
    errors = [f for f in ste.check_text(graph.read_text(encoding="utf-8"), ste.load_glossary(RULES)) if f[3] == "error"]
    assert errors == []
