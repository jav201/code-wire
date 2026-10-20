# Code-Wire — language rules (ASD-STE100)

> Status: decided 2026-10-19. The project is in English from now on. The chat with the author stays in Spanish.
> Rule C17 in `Metodologia.md` §5 points here. The check is `pilot/extractor/codewire_ste.py`.

## 1. Why

A contract must have one meaning for each reader. ASD-STE100 (Simplified Technical English) gives rules for this. Each word has one meaning. Each sentence says one thing. Short sentences are easier to check against the code.

## 2. Where the rules apply

- They apply to all English prose of the project: method, notes, pages, graph text, findings, docstrings, commit messages and backlog items.
- They do not apply to code, to the structured lines of a graph (`in: str path`), to tables or to quoted literals.
- Folder names and file names do not change. Old log entries do not change, because they are a record.

## 3. Rules that the tool checks

| Id | Rule | Level |
|---|---|---|
| S1 | A sentence in a numbered step has 20 words or fewer. Any other sentence has 25 words or fewer. | error |
| S2 | A numbered step gives one instruction. Do not join two steps with `;`, `, then` or `and then`. | error |
| S3 | A paragraph has 6 sentences or fewer. | error |
| S4 | Use the word that the glossary gives. Do not use the words in its column "Not". | error |
| W1 | Use the active voice. The tool finds most passive forms, but not all of them. | warning |

Inline code, a link or a quoted literal counts as one word.

Run the check:

1. Open a terminal in `evidence/pilot/extractor`.
2. Run `python codewire_ste.py FILE.md --glossary "../../../03 - Investigación/Language-STE.md"`.
3. Correct each error. Exit code 0 means no errors.

## 4. Rules that the tool does not check

- Use only the approved words of the STE dictionary. The tool cannot check this until we have the specification. The author must request it from ASD.
- Use an article (`a`, `the`) before a noun when possible.
- Do not use the `-ing` form of a verb as a noun or adjective.
- Use one tense where possible: the simple present.

The reviewer checks these rules by reading. The limits in §3 come from memory of the standard. Confirm them when we have the specification.

## Glossary

One word for each concept. A row with an empty "Not" column only defines the word.

| Use | Not | Meaning |
|---|---|---|
| node | function box | A function or method in the graph, drawn as a box. |
| entity | store, container | A place where data is used or kept (`[ ]`). |
| mark | annotation, tag | The `# node:` comment line above a def in the code. |
| thread | | The literal example chain: one line that follows the data from node to node. |
| recording | | The record of a real run that C16 compares the thread with. |
| trace | | The link from a node to a requirement. |
| drift | | A difference between the graph and the code that has no recorded reason (Metodologia §2, §8). A signature drift is one kind. |
| divergence | | A call between marked nodes that the graph does not declare (C15). It is one kind of drift. |
| marker | | A short flag inside a field: `(!)`, `wins`, `inferred`, `synthetic`. |
| prefix | | A word in parentheses before an input type, such as `(Callable)`. |
| literal anchor | | A value in an example line that C16 checks: `0x…`, text in backticks or in quotes. |
| assignment kind | | How `modify:` changes its target: `(replace)`, `(clear)` or `(append)`. |
| edge | | A line in `## Edges` that connects an output to an input or an entity. |
| arrow | | The line that a view draws for an edge. |
| overview | | The high-level view: node names, arrows and entities only. |
| change | touch, alter | To make something different. |
| remove | erase | To take something out. |
