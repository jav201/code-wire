# Code-Wire — canonical text and visual view (proposal Q26, 2026-10-17)

> Status: **decided 2026-10-18** (Q26, questionnaire on the page): C14, format B, no `**`, new fields, no ASCII overview in the source. Notation for optional: `X?` (Q27, decided 2026-10-18). Applied in `Metodologia.md` v2.4. It comes from Q19b: «In Excalidraw these diagrams are fascinating… but they must also exist only as text, for LLMs to read. In text the color is lost; I need that part reconciled» (original: «En excalidraw estos diagramas son fascinantes… pero también deben ser sólo en texto para lectura de LLMs. En texto se pierde color, necesito que se reconcilie esa parte»). v2.6 (2026-10-21): the section `## Boundary` (§7) and the layer catalog (§8).

## 1. Proposed principle
**The text is the source; the diagram is a view**. Each thing that the diagram shows with color, line weight, line style or position **comes from a field of the text**. No information exists only in the drawing.

This is the idea of the original sketch: «text source and color code as visual aids» (original: «fuente de texto y código de colores como ayudas visuales»). Color helps the eye. The data lives in the text.

Compliance test (proposed rule C14): remove all the styles from the diagram and generate it again from the text. No information must disappear. Also, a large language model (LLM) that reads only the text can answer each question that the diagram answers.

## 2. Reconciliation table: each visual code and its text source

| Visual code | Meaning | Text source (canonical) | Status on 2026-10-17 |
|---|---|---|---|
| Background color of the node | file | `module:` (each file gets a color of the palette; a tool generates the legend) | already in text |
| Bold | method (not function) | the name has the form `Class.method` (with a dot). Remove the `**…**` from the text: it was redundant and fragile for the parser | **changes**: remove `**` |
| Bars `\| \|` | node | node block (name line + one field on each line) | already in text |
| Brackets `[ ]` | entity | block `[Category: name]` | already in text |
| Double bar / dashed frame | subsystem | field `inner:` with the list of inner nodes | **new field** (today it is a free note «(subsistema)») |
| Shaded band | `(Callable)` input | `(Callable) A->B name` in `in:` | already in text |
| Arrow | connection | explicit list of edges `source.output ──▶ target.input` | already in text (the list of edges is the source; a tool generates the overview from it, §6) |
| `[1→N]` | iteration | `[1→N]` on the edge | already in text |
| Label `modify` | effect on an entity | `modify:` of the node | already in text |
| Dashed purple | alternative branch | on the edge: `when: <condition>` | **new** (today only in the drawing of 06a) |
| Dashed red | review finding | section `## Findings` with an id (`H-1`) and the node or edge that it anchors to; **not part of the contract** | **new** (today in free notes) |
| Translucent gray | discarded option | only in decision diagrams; source = verdict table | n/a to the graph |
| P2 strip (order for each event) | write/read order of a `[Data]` entity | block `sequence:` of the entity (see §3) | **new** |
| Thick border in P2 | the write that wins | `wins` at the end of the step | **new** |
| Red `(!)` in P2 | a read before the write that wins | marker `(!)` in the step | **new** |

The status column shows the state before the verdict of 2026-10-18. Since that verdict, all the items marked **new** or **changes** are decided. They are in `Metodologia.md` v2.4 and v2.5.

These are the **base codes**. They are always on. v2.6 adds layers on top of them: §8 has the catalog. A layer never uses a base code.

## 3. Example: P2 in text (real data from app)

The text already shows who writes and who reads: the `modify:` of each writer, and the edges from the entity to each reader. Thus the text does not repeat it. Only two things are new: the **assignment kind** in the `modify:` of the writer, and the **order for each event** in the entity.

```
TuiApp._build_mac_view_cache
req: …
…
modify: [Data: TuiApp._validation_issues] (replace)

TuiApp.update_a2l_view
req: …
…
modify: [Data: TuiApp._validation_issues] (clear)

[Data: TuiApp._validation_issues]
in: list[ValidationIssue]
desc: validation findings that the views read
sequence:
  dialogLoad: _apply_prepared_load wins → update_workspace_stats → update_validation_issues_view → update_a2l_tags_view (if there are tags) → update_memory_map
  projectLoad: update_workspace_stats (!) → _build_mac_view_cache wins → update_validation_issues_view → update_a2l_tags_view (if there are tags) → update_memory_map
  a2lChange: _build_mac_view_cache wins → update_validation_issues_view → update_a2l_tags_view
  fullUnload: _refresh_no_mac_validation → update_validation_issues_view → update_a2l_view wins → update_validation_issues_view
```

Assignments: `(replace)`, `(clear)`, `(append)`. Markers in `sequence:`: `wins` = the write that stays at the end of the event. `(!)` = a read that occurs before that write (it can read old data).

Here an LLM reads the same thing that the eye sees in the strip. It sees who writes, in what order, who wins, and which read comes too early. The color and the thick border are only the visual form of `wins`, `(!)` and the assignment kind. The aliases W1…R5 of the diagram belong to the view, not to the text.

## 4. Consequences
- **The parser becomes simpler**: no `**`, no free notes on the name line (finding 9 of the DDR pilot).
- **The diagrams should come from the text**, not from a script that someone writes by hand for each diagram (today `d1.py`–`d9.py` draw by hand). Until that generator exists, the review enforces the rule: all visual information must be in the text.
- **ASCII overview**: it leaves the source text (§6, reading 1). The list of edges is the source of the connections, and a tool generates the overview from it.

## 5. Questions for the verdict
1. Do we adopt the principle «text = source, diagram = view» as a rule (C14)?
2. Do we remove the `**` from the text, and take the bold from the dot in the name?
3. Do we add the new fields `inner:`, `when:` and `sequence:` (with `wins` and `(!)`)? Do we add the assignment kind in `modify:` and the `## Findings` section?

## 6. Compact format (2026-10-18)
Request: «in text there are many blank spaces… they are tokens to process. I need something more compact, maybe like a dictionary, without loss of ease of reading for a machine» (original: «en texto hay muchos espacios en blanco… son tokens que hay que procesar. Necesito que sea algo más compacto, tal vez a modo de diccionario, sin perder la facilidad de lectura para máquina»).

Measurement on the 15 nodes of the pilot (a script in the scratchpad of the session). **The session has no Claude tokenizer**: «~tokens» is an approximate count of words and signs. It is an indication, not an exact value.

| Format | Characters | Padding spaces | ~tokens |
|---|---|---|---|
| A · current, aligned | 4706 | 18 % | 1033 |
| B · one field per line, no padding | 3778 | 0 % | 979 |
| C · one line per node `{k: v; …}` | 3848 | 0 % | 980 |
| D · indented JSON | 4398 | 3 % | 1411 |
| E · JSONL | 4145 | 0 % | 1368 |
| ASCII overview alone | 1547 | 47 % | 297 |

How to read the table:
1. The largest waste is the ASCII overview (47 % spaces), and it also repeats the list of edges. Thus it leaves the source text, and a tool generates it as a view.
2. Without alignment, the text has ~20 % fewer characters. The token saving is smaller, because the tokenizer groups spaces.
3. JSON costs ~40 % more tokens (quotes, braces): 1411 against 979. In characters, D costs only 16 % more. Use it only as a derived export (the extractor already writes `extract.json`).
4. **Proposal: B.** It costs the same as C, and it gives one-line diffs for each field. This is important now, because each graph change at DDR needs a reason. C writes the full node again at each change.

```
build_validation_report
req: US-032, US-066, LLR-036.3, LLR-066.2
in: list[dict] records; LoadedFile? primary_file; dict? a2l_data; (Callable) list[ValidationIssue]->list[ValidationIssue] dedupe_issues; set[int]? overlapped_addresses
out: tuple(ValidationReport? report, list[ValidationIssue] issues, str? coverage_line)
func: composes the findings of MAC-only sessions and of cross-validation
module: app/tui/services/validation_service.py
inner: validate_mac_records, validate_artifact_consistency, validate_a2l_internal_issues
```

Changes from the current format: no padding. A `;` separates the inputs. Each input is `type name`, with no inner `:`. `X?` replaces `Optional[X]` (it is shorter and does not depend on the language). No `**`.

The same node in C is one line in the file. Its inputs use `,` because `;` already separates the fields, so the parser must count brackets:

```
build_validation_report {req: US-032, US-066, LLR-036.3, LLR-066.2; in: list[dict] records, LoadedFile? primary_file, dict? a2l_data, (Callable) list[ValidationIssue]->list[ValidationIssue] dedupe_issues, set[int]? overlapped_addresses; out: tuple(ValidationReport? report, list[ValidationIssue] issues, str? coverage_line); func: composes the findings of MAC-only sessions and of cross-validation; module: app/tui/services/validation_service.py; inner: validate_mac_records, validate_artifact_consistency, validate_a2l_internal_issues}
```

Verdicts (2026-10-18):
- **B** (the author asked for a recommendation).
- The ASCII overview goes out of the source. Excalidraw generates the view.
- C14: yes.
- Remove `**`: yes.
- The five new fields: yes.
- `X?`: not accepted as it is → Q27.

## 7. The section `## Boundary` (v2.6)
A graph of a flow slice declares its callers and consumers outside the slice in the section `## Boundary`. The section comes after `## Edges`. It has two kinds of lines:

- An edge with an `[Outside: name]` item at one end. The parser reads the item as an entity of the kind `Outside`.
- A line `discarded: <node>.<output> — <reason>`. It names an output that nothing uses, and why.

Example from the chip-open slice of app first-use:

```
## Boundary

[Outside: chip press] ──▶ OpenFolderChip._open_target
discarded: open_folder_in_file_manager.opened — the press path shows the status line, not the bool
```

Two edge forms of v2.6 go in `## Edges`, not in `## Boundary`:

```
OpenFolderChip._open_target ──▶ is_openable_chip_dir.root
resolve_chip_target.target ──▶ open_folder_in_file_manager.path
when: is_openable_chip_dir.openable
```

The first line is a caller edge: the source has no port, so `_open_target` computes `root` in its body. In the second edge, `when:` names an output, so that output counts as used. `Metodologia.md` §3.3 and §3.7 give the rules.

## 8. Layer catalog (v2.6, decided 2026-10-20)
A layer adds information to a view for one moment of the life cycle. Each layer has one source and one visual code, and no code is in two layers. "Not validated" means that this text defines the layer, but no real case used it yet. The first case that uses it can change it, with a written reason.

| Layer | Name | Source | Visual code | View | Status |
|---|---|---|---|---|---|
| L1 | Thread values | `examples:` | teal dashed box with the line in a monospace font | high | validated |
| L2 | Requirement trace | `req:` | violet tag on the node | high | validated |
| L3 | Types | `in:`, `out:` | monospace lines in the node | both | validated |
| L4 | Status | the markers and the marks (`Metodologia.md` §3.1) | NEW: dark pill; CHANGED: outlined pill; SHIPPED: no pill | high | validated (first-use) |
| L5 | Boundary | `## Boundary` | `[Outside: …]` in gray brackets | both | new in v2.6 |
| L6 | Code location | the marks (`file:line`) | gray monospace line under the node | low | validated |
| L7 | Real calls and drift | the extractor run (C15) | thin gray arrow with the call site; orange for a divergence | low | validated |
| L8 | Findings | `## Findings` | red dashed box (also a base code) | both | validated |
| L9 | Effects and security | `modify:`, I/O entities, `(Callable)` inputs | pink label on the node and pink arrow to the entity | high | not validated |
| L10 | Frequency | a recording and `[1→N]` | `×N` in a small circle | both | not validated |
| L11 | Test coverage | the recordings and the test ids | full dot: recorded; empty dot: no recording | both | not validated |
| L12 | State owner | `modify:` on `[Data]` entities | olive arrow: full line = writes, dotted line = reads | high | not validated |

Two codes are not the first choice, because a base code already used them. L1 is teal, because the amber band is the `(Callable)` code. L9 is a pink label, because a thick border is "the write that wins" in a `sequence:` strip.

A layer from a run (L7, L10, L11) gives the commit and the tests of that run in the legend. The presets are in `Metodologia.md` §4.
