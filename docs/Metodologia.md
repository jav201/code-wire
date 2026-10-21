# Code-Wire — function contract graph method (draft v2.6)

> Status: exploration. v2 (2026-10-15) starts from the author's sketch (`evidence/boceto-2026-10-15.jpg`, original in `G:\My Drive\dev-flow-radiografia\Scan_20261015_225327.jpg`): text notation instead of YAML; entities `[ ]` apart from the nodes; `modify:`; the graph frozen at PDR; link through a mark in the code. v2.1 (2026-10-16): the name **Code-Wire**; `req:` accepts more than one document; `(Callable)` as an input; purity includes reads; only two views; camelCase naming by default. v2.2 (2026-10-17): `(Callable)` with shading; app state = entity `[Data]`. v2.3 (2026-10-17, after the DDR pilot): PDR = faithful baseline, DDR = the graph agrees with the code (changes with a reason); closed, typed inputs; parameters with a default value go in; types as specific as possible; `module:` = path relative to the root, with no line. v2.4 (2026-10-18, Q25 and Q26): the text is the source and the diagram is a view (C14); format B, one field per line and no padding; no `**` (bold comes from the dot in `Class.method`); fields `inner:`, `when:`, `sequence:`, assignment kind in `modify:` and the section `## Findings`; O2 lifting (C15); optional type `X?` (Q27); examples as a literal thread; `modify:` on an input (Q28). 2026-10-19: literal anchors in `examples:` and C16 (the thread is checked against a recording). The open items are in `Preguntas-Abiertas.md`. 2026-10-19: the project moves to English, written to ASD-STE100 (C17, `Language-STE.md`). v2.5 (2026-10-19, E2): English keys (`module:`, `inner:`, `open:`, `sequence:`, `when:`, `examples:`, `req: to trace`); sections `## Nodes`, `## Entities`, `## Edges` and `## Findings`; `modify:` kinds `(replace)`, `(clear)` and `(append)`; example markers `inferred` and `synthetic`. v2.6 (2026-10-21, after the first real test, app first-use): the markers give the status NEW / CHANGED / SHIPPED (§3.1); numbers in backticks are anchors; the caller edge, `[Outside: …]` and the section `## Boundary` (§3.3, §3.7); a message is an edge with no lift; layers and presets on the two views (§4); a new PDR gate (§8).

## 1. Idea in one line
First, you design **what** the system does: a network of black-box functions. The data that flows between the functions connects them, and so do the entities that use that data. Then you write **how** each function works, with no limits. At the end, you review the code against the network.

## 2. Guiding principle: the graph is simple; PDR sets the baseline, DDR requires that it agrees with the code
The graph enters PDR together with the requirements. The complexity of the code grows from the simple graph: **do not fill the graph with implementation detail**.

**Revised 2026-10-17 (Q22).** At PDR, the graph is a **faithful approximation** of the final code: the baseline. Some specifications do not appear at PDR (for example, a parameter with a default value). At DDR, the graph **can change**, but each change needs a **relevant reason** that relates to the process, the design or the required function. When DDR closes, **the graph agrees with the code**. A change without a reason is drift, not an update.

Consequences:
- Nothing that you know only during implementation (file:line, progress state, who implements) is a field of the graph.
- If the DDR diff makes the graph change, the change records its reason (a trace to a requirement, ADR or design decision). It is not an addition of implementation detail.
- For each new field that someone proposes, ask: is it essential to the *what*, or does it come from other fields? If it comes from other fields, it does not go in.

## 3. Model

### 3.1 Node = one black-box function or method
The relation is **1 to 1**: a node is exactly one function or one method. It does not describe its algorithm.

```
Validate filePath
req: R-1
in: str filePath
out: str validFilePath
func: validates the path: format, and that the file and the folder exist
examples: (synthetic) filePath "logs/app.log" → validFilePath "logs/app.log"
module: io/paths.py
```

**Text format (Q26, decided 2026-10-18: format B).** The text is the **source** of the graph. The diagrams are views that a tool generates from it (C14). A node is a block: the name on the first line, then one field on each line, `field: value`, with no alignment or space padding. A blank line separates two blocks. In `in:`, a `;` separates the inputs, and each input is `type name`.

Do not use `**`: the dot in `Class.method` shows a method. Why B and not one line for each node? It costs the same number of characters. A change affects only the line of its field, and this is important at DDR, where each graph change needs a reason. Also, `;` separates the inputs, so the parser does not have to count brackets. JSON is only a derived export (~40 % more tokens, `Texto-Canonico.md` §6).

| Field | Required | Content |
|---|---|---|
| name | yes | a unique name; it obeys the design naming rules of the project |
| `in:` | yes | a **closed** list of `type name` items, separated by `;` (both parts are required): **all** the parameters, also the ones with a default value, written `type name = value`. **Optional type: `X?`** (Q27, decided 2026-10-18): the value can be missing (None / null); if it has a default value, write it (`Path? a2l_path = None`). This is Code-Wire notation, not notation of the language: write `Optional[X]`, `X \| None`, `?X`… from the code as `X?`. Not permitted: `…`, `etc.`, `(+ others)` or a name without a type (Q21, Q22). Put the prefix `(Callable)` on a function that comes in as data (see below) |
| `out:` | yes | **one output only**, `type name`; if there are more results, they are fields of a composite type; `None` if the node only changes entities |
| `func:` | yes | what the node does, in one or two lines; a description apart from the type and the name |
| `req:` | yes | ≥ 1 trace; it can point to **more than one document** (requirements, derived requirements, architecture decisions), for example `req: R-3, DR-7, ADR-2`. What is not *what* (volumes, resources) stays in those documents, not in the node |
| `examples:` | yes | ≥ 1 concrete `input → output` pair, written as a **literal thread** (see below); one line for each pair, repeatable. At PDR the stub returns it and the implementation must pass it; at DDR it comes from a real run |
| `module:` | yes | the file path **relative to the root folder of the repository** (and the class, if it is a method), with no line number (Q24): the `# node:` mark gives the line (§7). It is decided at PDR; it is an architecture decision |
| `modify:` | no | what the node changes, each item with its assignment kind: `(replace)`, `(clear)` or `(append)`. It can be an **entity** (`[Data: …]`, `[I/O: …]`) or **one of the node's own inputs**, by name, when the node changes that input in place (Q28): `modify: mem_map (replace)`, `modify: document.entries[].status (replace)`. **If you omit it, the node is pure** (§3.6) |
| `inner:` | if it is a subsystem | the list of the inner nodes that it calls (§3.5). C15 compares this list with the calls in the code |
| `open:` | if there is `Any` or a generic type without parameters | the name of the data and why it cannot be more specific (Q23) |
| `contract:` | no | preconditions, postconditions or invariants, only where an error is expensive |

**Examples as a literal thread (decided 2026-10-18, round 3)**. An example follows **one real data item** through the flow, with its literal value at each node. It replaces the old «shape + sample» format (counts and a short sample). The pilot tried that format, and it gave only part of the information.
1. **One thread for each flow.** Take **one** line or item from each input file or source. Choose the item that leads to the result of interest. In the pilot, this is `OVER_B`, where S19, A2L and MAC meet in the same issues. That line already shows the content and the format (S19 or HEX, for example).
2. **For each node, only what comes from that thread**. Give the literal value that goes in and the value that comes out. In parentheses, give how many there are in total (`record 3 of 4`, `tag 2 of 2`).
3. **Cut long values**. If a value is longer than about 160 characters, cut it with `…` and give the total size. Keep visible the keys that the next node uses.
4. **Name the source.** Each line starts with the source in parentheses: the test id (`AT-036a`) or the data case (`case_03`). At DDR the values come from a real run. Do not invent them.
5. **A node that the thread does not pass through** takes the thread of a different test that exercises it. This shows which test covers that node.
6. **Say what does not come from the thread**. If a node produces nothing for the data of the thread, write that (`OVER_B → no issue`).
7. **Literal anchors (2026-10-19).** Write each value that the line commits to as a literal anchor. A literal anchor is hexadecimal `0x…`, text in backticks, text in quotes `"…"` or text in `«…»`. The check takes an address/value pair (`0x1000: 0xAA`, `mem_map[0x1000] = 0xAA`) as one pair. Other text is prose that the check ignores. If the run did not show a value, write the marker in the source (`(AC-1, inferred)`), and C16 ignores it. Do not anchor a value that a different node sets, or a code constant (a limit, a threshold).
8. **Number anchors (v2.6).** A decimal number that the line commits to goes in backticks: `` `6` entries ``. The check compares it with the numbers of the recorded call. A number outside backticks and outside parentheses is a bare number. The check gives a warning for it, because the check does not compare it. A warning does not make the line fail. The counts in parentheses (`record 3 of 4`) are not anchors.
9. **Markers and status (v2.6).** The source marker tells why a line has no recording:
   - `synthetic`: behaviour that the design adds or changes. The code does not do it yet.
   - `inferred`: behaviour that the code already has, with no recording.

   The status of a node comes from the markers and from the marks in the code. It is not a field (§2):
   - **NEW**: the node has no def in the code.
   - **CHANGED**: the node has a def and at least one `synthetic` line.
   - **SHIPPED**: all the other nodes.

   Thus a node that keeps its signature but changes its behaviour shows as CHANGED. The extractor cannot see that change, because the signature is the same.

**Type + name:** the name obeys the design rules (domain vocabulary), and the type gives the name its context. **The type is as specific as possible (Q23):** if the data can have only a set of types, write that set (`dict[str, int]`, `int | str`). If it really can be any type (`Any`, a `dict` without parameters), write it like that. Give the reason in the `open:` field of the node (`open: payload — fields that the view sets; they change for each screen`). You can use primitives (`str filePath`). Declare a composite data item one time, as a named type with fields.

**Function as an input (`(Callable)`, decided 2026-10-16)**. If a node receives a different function as an argument, declare it in the input with the prefix `(Callable)`:

```
build_validation_report
in: …; (Callable) list[ValidationIssue]->list[ValidationIssue] dedupe_issues; …
```

**Optional function:** if the input can be missing, put the type of the function in parentheses, followed by `?`: `(Callable) (->datetime)? now_fn = None`. This is a function with no arguments that returns `datetime`, or nothing. `A->B?` is a function whose result can be missing.

The arrow comes from the node that implements that function (here `TuiApp._deduplicate_issues`). It has the same visual aid: **shading** (decided 2026-10-17, Q18b). The `(Callable)` line of the receiving node and the arrow that feeds it are on a shaded band. The font color is free.

**Modified input (Q28, decided 2026-10-18: option B)**. A node can change in place an object that it receives (a dictionary, a list, the fields of an object). Its `modify:` then gives the name of that input and its assignment kind. An entity is not necessary: entities are for I/O and for shared application state. An edge that leaves that input (`apply_change_document.mem_map ──▶ save_patched_image.mem_map`) carries **the value after the change**. If the node returns `None`, its example says what the modified input contains after the call.

**Composite output (decided 2026-10-15).** A function has one output only. Conditional results are fields. The graph does not branch for the internal logic.

### 3.2 Entities `[ ]` = where the data is used or kept
An entity **is not a node**. It is not a function: it is a final use of the data, or a place that keeps the data. Draw entities with brackets `[ ]`. Draw nodes with bars `| |`.

```
[Data: StackA]
in: str
desc: log entries classified as type A
```

Fields: category, name, `in:` (the type that it receives), `desc:` and, for a `[Data]` entity with more than one writer, `sequence:`.

**App state as a channel (Q19, decided 2026-10-17: option A)**. A data item that moves through a shared attribute (for example `TuiApp._validation_issues`) is a `[Data: …]` entity. The node that sets it has `modify:` to it. The node that reads it receives an arrow from it, and so that node is not pure (§3.6). The diagram does **not** show the order of the writes or which assignment wins. A separate visual aid next to the entity shows that: the **sequence strip for each event (P2, Q19b)**.

The text source of the strip is the `sequence:` field of the entity (Q26). It has one line for each event, with the steps in order. Put `wins` after the write that stays at the end of the event. Put `(!)` after a read that occurs before that write (it can read old data). Example: `projectLoad: update_workspace_stats (!) → _build_mac_view_cache wins → update_validation_issues_view`.

**Base catalog (open):** `Interface` (a screen, with a type: `[Interface:screen1:str]`), `I/O` (files, devices), `Database`, `API`, `Data` (shared structures in memory, such as a stack). The catalog **can grow**: a project declares the categories that it needs.

### 3.3 Edges = explicit arrows
- An arrow connects an output to an input, or a node to an entity.
- **The arrow sets the connection.** It is sufficient that the types agree. The names can be different (`validFilePath ──▶ filePath`).
- **Cardinality on the edge:** if an output `iter: T` feeds an input `T`, the edge has `[1→N]`. The receiving node runs one time for each item. This gives the number of calls.

```
Read file.fileLine ──▶ [1→N] Classify string log entry.fileLine
```

- **Alternative branch:** an edge that exists only under a condition has `when: <condition>` (for example `when: primary_file is None`). The view draws it purple and dashed. This does not contradict the composite output. The condition decides which flow exists. It does not branch the output of a node.

- **`when:` with an output (v2.6).** The condition can name an output: `when: is_openable_chip_dir.openable`. The edge is then a use of that output, and C3 counts it as used. Use this form when a `bool` output only selects an edge.
- **Caller edge (v2.6).** The source of this edge is a node with no port: `OpenFolderChip._open_target ──▶ is_openable_chip_dir.root`. It means that the source node computes the value in its own body and passes it. C2 counts the input as fed.
- **Outside item (v2.6).** `[Outside: name]` is a caller or a consumer outside the graph, for example a key press or the event loop of a framework. It uses the bracket form of an entity. The section `## Boundary` declares it (§3.7). An edge from an outside item is the `external` of C2.
- **Message (v2.6).** A framework message (for example `post_message` in Textual) is not a call, so C15 cannot see it. Declare it as a usual edge. C15 does not look for a call for that edge.

**Branched arrow = same value (Q25, 2026-10-18).** If the output of a node goes to more than one consumer, all the consumers receive the same value. The node runs one time for each flow (except with `[1→N]`). This is a contract, not a guarantee. DDR checks it with C15. When a node runs two times, the review shows the **overlap view** (diagram 12).

### 3.4 Granularity
Only functions that **transform a domain data item** are nodes. Utilities (formatting, logging, helpers) stay inside their node. Rule: if you remove a function and no data item gets a different history, it is not a node.

### 3.5 Subsystems
A node can be a subsystem whose inside is a different graph. From outside, it behaves like any other node (rule C9). The `inner:` field declares it (the list of inner nodes). The view draws it with a double bar.

### 3.6 Pure node (derived)
A node is pure if it **has no `modify:`**, not on entities and not on its inputs (Q28). Also, **it receives no arrow from an entity** (decided 2026-10-16, Q17). A read from a file, a database or a shared state is also an effect. The output of a pure node depends only on its inputs. Its examples alone test it, its stub is trivial, and it is the easiest task to delegate. At DDR, a pure node that uses an entity is drift.

### 3.7 Boundary of a flow slice (v2.6)
A graph often covers only a slice of the application: the flows that a change touches. A slice has callers and consumers outside it. The section `## Boundary` declares them, so that C2, C3 and C4 do not report the edge of the slice as a problem.

```
## Boundary

[Outside: chip press] ──▶ OpenFolderChip._open_target
discarded: open_folder_in_file_manager.opened — the press path shows the status line, not the bool
```

- A line with `[Outside: …]` is an edge from or to an outside item. An outside item is a source or a sink for C4. C10 does not ask for a node that writes it.
- A `discarded:` line names an output that nothing uses, and gives the reason after `—`. C3 counts it as declared. If the reason is not a design decision, write a finding (`## Findings`) instead.
- Do not put a node or an entity of the slice in `## Boundary`.

## 4. Views and visual notation
One graph, **only two views** (rule, 2026-10-16). There are no intermediate views:
- **Low level (detail):** **all** the nodes with their full contract (§3.1), also the nodes inside subsystems. Each arrow goes to the exact node that consumes the data. If an input crosses the frame of a subsystem, the arrow continues to the inner node. The frame of the subsystem only groups the nodes.
- **High level (overview):** only node names, arrows and entities. A subsystem can show as one box. **A tool generates this view from the text** (today with Excalidraw). Do not write it by hand as an ASCII drawing in the source text (Q26: it repeated the edges and was ~47 % spaces).

Why: some diagrams show some nodes in full and other nodes in short form. Some diagrams show inputs that stop at the frame and not at a node. Such a diagram does not agree with its text. With two views, each nested node shows in full.

Visual aids (standard, simple):
- **Background color for each file** (`module`).
- **Normal font = function; bold = method** (it comes from the dot in `Class.method`).
- Each visual code comes from a field of the text (C14). The full table is in `Texto-Canonico.md` §2. Its status column shows the state on 2026-10-17.
- Bars `| |` = node; brackets `[ ]` = entity.

**Layers and presets (v2.6, decided 2026-10-20).** Each moment of the life cycle needs different information on the diagram. For example, the high view with the thread values helps to prototype and to trace the requirements. The low view helps at DDR. Thus a view can show **layers**, and a **preset** is a fixed set of layers for one moment. The catalog of the 12 layers, with their visual codes, is in `Texto-Canonico.md` §8.

| Preset | View | Layers | Use |
|---|---|---|---|
| Prototype | high | L1 thread values, L2 requirement trace, L5 boundary | Before PDR: check that the thread meets each requirement |
| PDR | high | L2, L3 types, L4 status, L5 | At PDR: review the contracts of the NEW and CHANGED nodes |
| DDR | low | L6 code location, L7 real calls and drift, L8 findings | At DDR: the code obeys the graph. The low view always has the full contract |
| Effects | high | L9 effects, L5 | A security review: what the program writes, and what comes from outside |

Rules for the layers:
1. Each visual code belongs to one layer only. The base codes of `Texto-Canonico.md` §2 do not change.
2. Each layer has one source: a field of the text, or the output of a tool. A layer from a run gives the commit and the tests of that run. This is how C14 applies to a layer that does not come from the text.
3. A diagram uses a preset, or its legend lists each layer that it adds.
4. Each layer has a status: validated or not validated. The first real case can change a layer that is not validated, with a written reason.
5. A layer does not add a field to a node.

## 5. Coherence rules (a machine can check them)

| # | Rule | What it finds |
|---|---|---|
| C1 | Each arrow joins equal types | contracts that do not fit |
| C2 | Each input has an incoming arrow: from a node port, from a caller edge, from an entity, or from an `[Outside: …]` item (`external`) (§3.3) | data that nothing produces |
| C3 | Each output that is not `None` has ≥ 1 outgoing arrow, or a `when:` names it, or `## Boundary` has a `discarded:` line for it | data that nothing uses |
| C4 | Each node is reachable from a source and reaches an entity or a sink. An entity and an `[Outside: …]` item are sources and sinks | islands and dead ends |
| C5 | Each node traces to ≥ 1 requirement | functions with no reason to exist |
| C6 | Each functional requirement has ≥ 1 node | requirements with no coverage |
| C7 | The names of nodes, entities and types are unique | ambiguity |
| C8 | The graph declares each cycle explicitly | accidental loops |
| C9 | Balance between levels: a subsystem shows on the outside exactly what its subgraph consumes and produces | hidden inputs, lost outputs |
| C10 | Each target of `modify:` is a declared entity or an input of the node itself (Q28), and each entity has ≥ 1 node that writes or reads it | effects with no owner, orphan entities |
| C11 | Each name obeys the naming rules of the project (each project sets them; the default is **camelCase**) | inconsistent vocabulary |
| C12 | Closed, typed inputs: no `…`, `etc.`, `(+ …)` or names without a type; each parameter of the code appears, with its default value if it has one | ambiguity: «there are more; I do not know how many or which» |
| C13 | Each `Any` or generic type without parameters has its line in `open:` | vague types with no reason |
| C14 | Text = source, diagram = view: each visual code (color, line weight, line style, position) comes from a field of the text; if you remove the styles and generate the diagram again, no information disappears | information that exists only in the drawing |
| C15 | Each call between marked nodes, lifted to the marked node that contains it (O2, reflexion type), has a declaration in the graph (`inner:` or an edge); if not, it is a divergence | calls that nobody planned; a node that runs more times than the graph says (Q25) |
| C16 | Each `examples:` line whose source has a recording holds: its literal anchors appear in one same recorded call of the node (inputs, output, modified inputs after the call, files that the node reads or writes) | an out-of-date thread: the example no longer describes what the code produces |
| C17 | All English prose of the project follows the language rules of `Language-STE.md` (ASD-STE100): short sentences, one instruction for each step, one word for each concept | text that two readers understand in two different ways |

## 6. Life cycle

```
Requirements → Graph → Coherence → Stubs → [PDR] → Implementation in waves → Code vs graph review → [DDR]
```

1. **Graph.** Start from the requirements: nodes, entities, arrows. Only the *what*.
2. **Coherence.** Apply the rules of the PDR gate (§8). C15 applies at DDR. C16 applies to each line that has a recording, and C17 applies to all text.
3. **Stubs.** Generate each node as a function with its mark (§7). The function returns the output of its example. The network runs from end to end without one algorithm. **Here the graph becomes the baseline (PDR)**. At DDR it can change with a reason, and it must agree with the code (§2).
4. **Implementation in waves.** Implement the nodes in topological order, and the nodes of one wave in parallel. A node passes acceptance when it passes its examples and obeys its type. The implementation phase sets the bounded repair and the escalation.
5. **Review (DDR).** A tool extracts the real graph from the code. The review compares it with the design graph (diff, §8). The graph gets no new fields.

The **progress** (stub / implemented / verified) is not a field of the graph. It comes from the mark in the code and from the example tests.

## 7. Node ↔ code link: mark in the code
Each function or method that implements a node has its node name and its requirement:

```python
# node: validate_file_path  [R-1]
def validate_file_path(file_path: str) -> str:
    ...
```

- The relation is 1 to 1: one node, one mark.
- The extractor finds the marks in a deterministic way. The `file:line` comes from the marks, not from the graph.
- Thus everything ties to the trace of the engineering system: requirement → node → code.

## 8. Reviews

### PDR — the *what* is closed
**The gate (v2.6).** The table shows where each rule stops a review. In the first real test, the threads and the recordings found all the major problems. C2 and C12 on the NEW nodes found four minor ones. C1, C3 and C4 cost many edges on a slice, and they found no design problem.

| Rule | Gate at PDR | Gate at DDR |
|---|---|---|
| C16 threads: each NEW and CHANGED node has ≥ 1 line with an anchor; each recorded line holds; a probe runs each arm with no recording | yes | yes |
| C2 and C12 on the NEW and CHANGED nodes | yes | yes |
| C5–C11, C13, C14, C17 | yes | yes |
| C1, C3, C4, and C2 on the SHIPPED nodes | a list, not a gate | yes |
| C15 | no | yes |

- The rules of the PDR gate have no violations.
- Each node has ≥ 1 example and its `module`.
- Each stub has its mark. The skeleton runs from end to end.
- The requirement ↔ node trace is complete.

### DDR — the code obeys the graph
- The rules of the DDR gate (the table above) have no violations.
- Each node has exactly one mark in the code, and each mark belongs to a node.
- Each node passes its examples: C16 shows no drift against the recording of each source (`cw_record_plugin.py` + `codewire_examples.py`). A list shows each source with no recording as not checked. Each node with a `contract` has a verified contract.
- **When DDR closes, the graph agrees with the code.** Each graph change since PDR has a record of its reason.
- The lifted calls (C15) have no open divergences. The review examines each repeated call in the overlap view, with its path. The path shows where each call comes from and where it goes: it complements, duplicates or diverges.
- The review findings go in the `## Findings` section of the text: an id (`H-1`), the node or edge that they anchor to, and one-line fields. **They are not part of the contract.** The view draws them in dashed red.
- The diff has no open differences. **Kinds of drift:**
  - a node without code
  - a mark without a node
  - an unexpected or missing arrow
  - a different type
  - a different `module`
  - a pure node that reads or changes an entity
  - a changed entity that `modify:` does not declare
- Correct each difference in the code, or record it as a design decision. Never ignore a difference.

## 9. What the method is NOT
- **It is not a block language that generates code** (unlike Simulink/SCADE). The block declares the interface, and the body is free.
- **It does not describe algorithms.**
- **It does not replace tests.**
- **It is not dev-flow.** It runs in parallel. It shares the requirement trace and the PDR/DDR vocabulary. It gets a new evaluation after the pilot.

## 10. Example (from the sketch)

In format B (v2.5). A tool generates the visual form from this text. The sketch has no code, thus the `module:` paths are synthetic:

```
## Nodes

Validate filePath
req: R-1
in: str filePath
out: str validFilePath
func: validates the path format, and that the file and the folder exist
module: logtool/paths.py
examples: (synthetic) filePath "logs/app.log" → validFilePath "logs/app.log"

Read file
req: R-2
in: str filePath
out: iter[str] fileLine
func: opens the file and gives it line by line as an iterable
module: logtool/reader.py
examples: (synthetic) filePath "logs/app.log" (3 lines) → fileLine (2 of 3) "A 10:02 disk full"

Classify string log entry
req: R-3
in: str fileLine
out: None
func: classifies the log entry and puts it on a stack by its type
module: logtool/classify.py
modify: [Data: StackA] (append); [Data: StackB] (append)
examples: (synthetic) fileLine "A 10:02 disk full" → None; [Data: StackA] receives "A 10:02 disk full" (1 of 1); [Data: StackB] no change: the line is type A

## Entities

[Data: StackA]
in: str
desc: log entries classified as type A

[Data: StackB]
in: str
desc: log entries classified as type B

## Edges

Validate filePath.validFilePath ──▶ Read file.filePath
Read file.fileLine ──▶ [1→N] Classify string log entry.fileLine
```

**Thread of the example.** The log has 3 lines (`B 10:01 user login`, `A 10:02 disk full`, `B 10:03 user logout`). The thread follows line 2 from node to node. The source is `(synthetic)` because the sketch has no code and no run behind it: C16 does not check it. In a real project, the source is the id of a test, as in the pilots.

None of the three nodes is pure by Q17. `Validate filePath` queries the file system (does the file exist, does the folder exist), and `Read file` reads the file. In a full graph, both receive an arrow from `[I/O: log file]`, which the sketch does not draw. `Classify` changes two entities. A pure node in this domain is, for example, a node that only validates the **format** of the path.

## 11. Reserved for the implementation phase
Useful, but outside the graph and outside the query that you use to understand code:
- **Implementer assignment** (a model or a person for each node).
- **View for a large language model (LLM) with a token budget**, generated on demand. It shows the node with its contract and examples, the types that it uses and the signatures of its neighbors.
- **Specialized viewer** (an idea for the future, 2026-10-16): a dedicated application to show these graphs and to switch between the two views.
