# Code-Wire

Code-Wire describes a part of a program as black-box functions, each with a typed contract and concrete examples written from what the function must do. Running those examples, and reading who really calls each function, is where its findings came from.

Status: v3.1, the core only (2026-10-26). The history is in git.

## Read first

1. `docs/Metodologia.md`: the method, in seven short sections.
2. `docs/Notation-Grammar.md`: the exact form of each line of a graph text, with examples that the tests read.
3. `docs/Review-Method.md`: reviewing a whole code base by modules, with agents, and the gates that keep each step from being skipped.

## Use it

On a change, or in an audit of existing code: `docs/Metodologia.md` §5 gives the steps. In short: write an example for each function from its requirement, read the callers that the extractor lists, run the examples, and keep a failing test for each defect. Do not use it for a small change that one reader can see whole.

## Tools

Python 3, standard library only. Run them from the root of this repository, with `tools/` on `PYTHONPATH`.

| Tool | What it does | Command |
|---|---|---|
| `tools/cw_record_plugin.py` | Records each node while the pytest tests run, into an event log | `CW_GRAPHS=<graph.md> CW_EVENTS=<out>/ev.jsonl pytest -p cw_record_plugin` |
| `tools/cw_record_run.py` | Records a probe script; a printed line can start a step | `python tools/cw_record_run.py --graph <graph.md> --path <code> --step-regex "^== (U\d+\.\d+)" --events ev.jsonl probe.py` |
| `tools/cw_textual.py` | For a Textual app: the root crosses messages, dialogs and workers | `CW_ADAPTERS=textual` |
| `tools/codewire_events.py` | Reads an event log: the examples and paths of each root, a root × node matrix, the first step where two logs differ | `python tools/codewire_events.py report ev.jsonl` · `… diff a.jsonl b.jsonl` |
| `tools/codewire_examples.py` | C16: checks many example lines against a recording at once (exit 1 if a recorded line does not hold) | `python tools/codewire_examples.py --graph <graph.md> --trace ev.jsonl --out report.md` (one log for every thread, or `--trace <thread>=ev.jsonl` for each) |
| `tools/codewire_extract.py` | Compares the marks and the contracts of the graph with the code, and lists the real calls (exit 1 on a drift) | `python tools/codewire_extract.py --repo <repo> --graph <graph.md> [--path <folder>] --out <dir>` |
| `tools/codewire_lint.py` | Lists the lines of a graph that the parser does not read (exit 1 if any) | `python tools/codewire_lint.py <graph.md> [--json parse.json]` |
| `tools/codewire_review.py` | The gates of the review by modules: writes each agent's brief from `tools/review_briefs.md`, checks a map, checks a review (exit 1 when a step is skipped) | `python tools/codewire_review.py brief\|map-gate\|review-gate --work <dir> --group <G> [--kind map\|code\|tests\|cohesion]` |
| `tools/codewire_marks.py` | Writes the marks from a graph into a throwaway worktree | `python tools/codewire_marks.py --repo <worktree> --graph <graph.md>` |

Tests: `python -m pytest tests` (158 tests).

## Known limits

- The tools read Python code only.
- A value that a worker writes later is not in the values after the call.
- In a usual example line, C16 uses the root but not the step. Under a probe script, every call has the root `harness`.
- C16 checks that a value is there, not its order, and not that a text is absent.
