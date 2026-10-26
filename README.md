# Code-Wire

Code-Wire describes a part of a program as black-box functions, each with a typed contract and concrete examples, and checks each example against a recording of the real code. In five real uses, every finding came from that check.

Status: v3, the core only (2026-10-25). The history is in git.

## Read first

1. `docs/Metodologia.md`: the method, in seven short sections.
2. `docs/Notation-Grammar.md`: the exact form of each line of a graph text, with examples that the tests read.

## Use it on a change

1. Write the nodes that the change adds or changes. Each has typed inputs, one output and an example line marked `unrecorded`.
2. Write each new function as a stub with its mark `# node: <name>  [<req>]`.
3. Implement the code.
4. Record the threads (the tests, or a probe script), then run C16 and the extractor.
5. The change is done when C16 has no drift and no `unrecorded` line for the changed nodes, and the extractor has no drift.

Do not use it for a small change that one reader can see whole.

## Tools

Python 3, standard library only. Run them from the root of this repository, with `tools/` on `PYTHONPATH`.

| Tool | What it does | Command |
|---|---|---|
| `tools/cw_record_plugin.py` | Records each node while the pytest tests run, into an event log | `CW_GRAPHS=<graph.md> CW_EVENTS=ev.jsonl pytest -p cw_record_plugin` |
| `tools/cw_record_run.py` | Records a probe script; a printed line can start a step | `python tools/cw_record_run.py --graph <graph.md> --path <code> --step-regex "^== (U\d+\.\d+)" --events ev.jsonl probe.py` |
| `tools/cw_textual.py` | For a Textual app: the root crosses messages, dialogs and workers | `CW_ADAPTERS=textual` |
| `tools/codewire_events.py` | Reads an event log: the examples and paths of each root, a root × node matrix, the first step where two logs differ | `python tools/codewire_events.py report ev.jsonl` · `… diff a.jsonl b.jsonl` |
| `tools/codewire_examples.py` | C16: checks each example line against a recording; the report starts with the lines that no recording backs | `python tools/codewire_examples.py --graph <graph.md> --trace <thread>=ev.jsonl --out report.md` |
| `tools/codewire_extract.py` | Compares the marks and the contracts of the graph with the code, and lists the real calls | `python tools/codewire_extract.py --repo <repo> --graph <graph.md> [--path <folder>] --out <dir>` |
| `tools/codewire_lint.py` | Lists the lines of a graph that the parser does not read (exit 1 if any) | `python tools/codewire_lint.py <graph.md> [--json parse.json]` |
| `tools/codewire_marks.py` | Writes the marks from a graph into a throwaway worktree | `python tools/codewire_marks.py --repo <worktree> --graph <graph.md>` |

Tests: `python -m pytest tests` (134 tests).

## Known limits

- The tools read Python code only.
- A value that a worker writes later is not in the values after the call.
- In a usual example line, C16 uses the root but not the step.
