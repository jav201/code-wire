# Code-Wire — reviewing a code base by modules

> The method, as the operator set it (2026-10-26), and the three gates that keep agents — and the orchestrator — from skipping a step. Used once on a 26.4k-line application (8 groups): 46 defects proven by failing tests, about 112 test findings proven by mutants.

## The steps

1. **Group the requirements by module.** One chapter per functional module, in the file where the requirements live. Each row moves as it is, exactly once. Each module is small enough for one agent (about 7k lines).
2. **Map each module.** One agent per module writes the map in Code-Wire graph text: one node per function, with its requirements, contract and the tests that call it. The map is the reading base for the reviewers; it does not look for defects.
3. **Review on the map.** Each map goes to two agents: one reviews the code (a defect counts only with a test that fails), one reviews the test cases (a weak test counts only with a mutant that survives).
4. **Review the traces.** The orchestrator checks requirement → node → test and code → node, and hands each reviewer only the nodes of other modules that carry a requirement of its chapter.
5. **Review cohesion.** When every module is done, two agents read all the results and look for what crosses modules: rows reviewed on neither side, contradictions, shared causes, gaps. The orchestrator matches what they say against the traces. The map only photographs the code and its traces: a discrepancy is resolved in the design artifacts (requirement, user story, V&V, evidence), and the code follows them.

## What each step must not do

| Step | Must not |
|---|---|
| 1 | change a row; put a row in two chapters |
| 2 | run a test or the app; change anything outside `_map/` |
| 3, code | change product code |
| 3, tests | install a package; leave a mutant in the code |
| 4 | hand over another module's whole map; write "review it there" (the chapter that holds a row owns its review) |
| 5 | change files |

## The gates (`tools/codewire_review.py`)

The work folder holds `base/` (the code, exported without history), one copy per group, `groups.csv` (`id,group`) and `files.csv` (`file,group`).

- `brief --kind map|code|tests|cohesion` writes an agent's brief from `tools/review_briefs.md`. No brief is written by hand. It refuses `code` and `tests` until the group's map passed and its traces are newer than every map, and `cohesion` until every group passed its review gate.
- `map-gate --group G` passes when the map has no line the parser does not read, every function of the group's files has a node (module + name), every requirement id and every cited test exists, and nothing outside `_map/` changed (a `# node:` comment line is allowed). On a pass it rewrites `TRACES.md` and `cross-nodes.md` for every group whose map passed.
- `review-gate --group G` passes when the code reviewer's tests fail on the current code and the product code of both copies is unchanged.

Each command exits 1 on a failure and says why.
