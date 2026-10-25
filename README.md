# Code-Wire

Code-Wire is a method to design software as a graph of black-box functions. First you write **what** the system does: nodes with typed inputs, one output and examples, plus the arrows between them. Then you write **how** each function works. At the end, a tool compares the code with the graph.

Status: draft v2.6, an exploration. The method had one pilot on a real Python application (reverse direction: from code to graph). It also had one real test in the forward direction (app first-use). v2.6 comes from that test. This repository is the source of the method text and of the tools.

## Read first

1. `docs/Metodologia.md`: the method. Read §1–§8 before you write a graph. §10 has a full small example.
2. `docs/Texto-Canonico.md`: the text format of a graph (format B). The text is the source, and a diagram is only a view (rule C14).
3. `docs/Notation-Grammar.md`: the full form of each line of format B, with examples and the warnings of the tools.

The documents refer to evidence of the pilot, for example `evidence/...`. That evidence is not in this repository.

## Apply the method to a real case

There are two directions.

**Forward (PDR → DDR): the graph first, the code after.**

1. Write the requirements with ids, for example `R-1`.
2. Write the graph in format B (`## Nodes`, `## Entities`, `## Edges`). Use `examples/logtool-graph.md` as a model. For a slice of the application, add `## Boundary` with the callers and consumers outside it (`docs/Texto-Canonico.md` §7). Add `## Routes` with the entry points (`docs/Metodologia.md` §3.8).
3. Check coherence: apply the rules of the PDR gate (`docs/Metodologia.md` §8).
4. Write each node as a stub with its mark `# node: <name>  [<req>]`. The stub returns the output of its example.
5. Implement the nodes.
6. Run the extractor, and correct each difference in the code or record it as a design decision (DDR).

**Reverse: from code that exists to a graph.**

1. Choose one flow of the application, not all of it.
2. Write the graph of that flow from the code: one node for each function with a domain step.
3. Put the marks in a throwaway worktree with `codewire_marks.py`.
4. Run the extractor. Each difference is a finding about the graph or about the code.

## Tools

The tools are Python 3 with the standard library only. Run them from the root of this repository.

| Tool | What it does | Command |
|---|---|---|
| `tools/codewire_extract.py` | Compares the `# node:` marks in the code with the graph, and applies C15 to the calls between nodes | `python tools/codewire_extract.py --repo <repo> --graph <graph.md> --out <dir>` |
| `tools/codewire_marks.py` | Writes the marks from the graph into a throwaway worktree | `python tools/codewire_marks.py --repo <worktree> --graph <graph.md>` |
| `tools/cw_record_plugin.py` | A pytest plugin that records the inputs and outputs of each node while the real tests run | `CW_GRAPHS=<graph.md> CW_OUT=trace.json pytest -p cw_record_plugin`, with `tools/` on `PYTHONPATH` |
| `tools/codewire_events.py` | The event log of the recorder: each call with its root (the entry point that started it, or `harness`), its parent and a hash of its values | the plugin writes `cw-events.jsonl` (`CW_EVENTS`); `python tools/codewire_events.py report <log>` gives the matrix, the variants and the examples of each root; `… diff <a> <b>` gives the first step that differs |
| `tools/cw_textual.py` | An adapter for Textual apps: the root and the parent cross messages, dialogs, workers and later calls; each event gets the screen state (`ui`) | `CW_ADAPTERS=textual`, and `CW_UI=#status` for the text of widgets |
| `tools/cw_record_run.py` | Records a script (a probe), not only a pytest run; a printed line can set the step | `python tools/cw_record_run.py --graph <graph.md> --path <code> --adapters textual --step-regex "^== (U\d+\.\d+)" probe.py` |
| `tools/codewire_examples.py` | Checks the `examples:` lines against a recording (C16): also a root, `expect none` and the `offers:` of an `[Interface]` entity | `python tools/codewire_examples.py --graph <graph.md> --trace <id>=trace.json --out report.md` |
| `tools/codewire_lint.py` | Reads a graph text in full, lists the warnings of the grammar (G1 to G12) and can write the parse as JSON | `python tools/codewire_lint.py <graph.md> [--json parse.json]` |

Tests: `python -m pytest tests` (172 tests).

In the report of `codewire_examples.py`, `ok` means that the line has an anchor and that the anchor is in the recording. A line with no anchor gets `no_anchor`. A node with no code yet gets `no_def`, because the recorder skips it and lists it in `_skipped`. A bare number gets a warning, because the check does not compare it. The report also gives the status of each node: NEW, CHANGED or SHIPPED.


## Known limits

- The tools read Python code only.
- The node status comes from a recording: the recorder skips a node with no def. With no recording, the tools do not give the status.
- The questions and the verdicts behind the method (`Open-Questions.md`) are not in this repository. They are in the project vault, in English.
