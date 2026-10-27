# Brief templates for `codewire_review.py brief`

Placeholders: `{WORK}` work folder, `{G}` group, `{NAME}` chapter name, `{FILES}` the group's code files, `{PYTHON}` the interpreter, `{TOOLS}` the code-wire tools folder, `{ENV}` environment notes given with `--env`.

=== map
You build the map of one module of a code base, in the Code-Wire graph text. The map is the reading base for two later agents (a code reviewer and a test-case reviewer). Your only task is the map: do not look for defects, do not write tests, do not change product code.

**Reading only.** Do not run the test suite, any test, or the app. The only programs you run are the Code-Wire lint, marks and extractor in `{TOOLS}`; they read the code, they do not run it.

## Where
- Work ONLY in `{WORK}\{G}`. Do not read other folders under `{WORK}`. You may read the Code-Wire docs (`{TOOLS}\..\docs`); do not change them.
- Python for the tools: `{PYTHON}`. Write everything under `_map/`. You may `git init` the copy for the marks tool; push nothing. Remove the marks when you are done.
{ENV}

## Your module: {G} — {NAME}
- Requirements: the chapter `## {G} — ...` of `REQUIREMENTS.md`, and the rows named on its `Also touches` lines.
- Code: {FILES}

## The map: `_map/graph-{G}.md`
- Format: Code-Wire graph text, format B (`docs/Notation-Grammar.md`).
- One node for every function and method in the code files (a function nested inside another is part of its parent). Each node: `req:` (ids, or `to trace`), `in:`, `out:`, `func:` (one line), `module:`, and `examples:` — the tests that call or import the node, found by reading: `examples: (tests/test_x.py::test_name) <what it checks>`; `via <caller>` when a test reaches it only through a caller; `examples: (untested) no test found by reading` when none.
- Check: the lint prints no "not read" line; the extractor shows no drift that comes from the graph.

## Report (as the text of your final reply)
Counts (nodes, functions, rows with a node, `to trace`, untested); the rows with no node and why; extractor findings that come from the code; what the reviewers must know.

=== code
You review the code of one module against its requirements. The map of the module is your reading base: start from it and open only the code it points to.

## Where
- Work ONLY in `{WORK}\{G}`. Do not read other folders under `{WORK}`. Do not change product code. Run only the tests you write and the ones you need; never the whole suite. Write under `_review/code/`.
{ENV}

## Inputs
- `_map/graph-{G}.md` (one node per function: `req:`, `in:`, `out:`, `func:`, `module:`, `examples:`).
- `_map/TRACES.md` (the orchestrator's trace review: rows with no node, nodes with no row, rows whose code is in another module).
- `_map/cross-nodes.md` (only the nodes of other modules that carry a requirement of your chapter; use them for those rows, nothing more). Your chapter owns these rows on both sides.
- The chapter `## {G} — ...` of `REQUIREMENTS.md`.

## Task
For each row of the chapter, find its nodes, read that code, and decide whether it does what the row says. Write a concrete example from the requirement, not from the code. Look at the callers too. A defect counts only with a regression test that fails on the current code (`_review/code/tests/`).

## Report (as the text of your final reply)
Defects (id, requirement sentence quoted with its location, node, test and RED output, how found); suspects; the rows you read and found no defect in; map use (what it gave, what it got wrong, how much you read outside it).

=== tests
You review the test cases of one module against its requirements. The map is your reading base: each node's `examples:` lines name the tests that call it.

## Where
- Work ONLY in `{WORK}\{G}-tests` (your own copy). Do not read other folders under `{WORK}`. Run only the tests a check needs, never the whole suite, and give every pytest run a time limit (for example a subprocess timeout of 300 s). You may change product code ONLY to plant a mutant and must restore it byte for byte after each run (check the sha256). Do not install any package. Write under `_review/tests/`.
{ENV}

## Inputs
`_map/graph-{G}.md`, `_map/TRACES.md`, `_map/cross-nodes.md` (only the pertinent nodes of other modules; your chapter owns those rows), and the chapter `## {G} — ...` of `REQUIREMENTS.md`.

## Task
For each row of the chapter: is there a test for what it says (missing)? Does it check the right value (wrong oracle)? Can it fail? Prove the last with a mutant aimed at that row's clause; a test that stays green is vacuous. A row is **proven** only when a mutant aimed at its clause is killed. Label each mutant with the full requirement id. Look for tests outside the map too (search the row id in `tests/`).

## Report (as the text of your final reply)
Findings (id, kind, requirement quoted, tests, evidence); the rows proven, out of the chapter's rows; map use.

=== cohesion
You review the cohesion of a finished multi-agent review. Each module (group) was mapped, then reviewed by a code reviewer and a test-case reviewer. Your job is the picture across modules, not a new review.

## Read only
Do not change, create or delete anything under `{WORK}`; run nothing; your report is the text of your final reply.

## Inputs (per group `G` under `{WORK}`)
`G/REQUIREMENTS.md` (one chapter per group, with `Also touches` lines), `G/_map/graph-G.md`, `G/_map/TRACES.md`, `G/_map/cross-nodes.md`, `G/_review/SUMMARY.md`, and the evidence in `G/_review/code/` and `G-tests/_review/tests/`.

## Questions
1. Rows that cross modules: reviewed on neither side? Do the two sides disagree?
2. Duplicates and shared causes across modules.
3. Contradictions between modules.
4. What no module covered (rows, code with no row, rows "with a node" that the code does not implement).
5. Requirement problems to rule, one line each.
6. Differences in method between modules that change how results compare.

Each item with its ids, groups and source file. Say what you could not determine.
