# Code-Wire — grammar of the text format (format B)

> Status: new on 2026-10-23 (E7a), for the notation of v2.6. This file gives the full form of each line of a graph text. `Metodologia.md` §3 gives the meaning of each part, and `Texto-Canonico.md` gives the reasons for the format. If this file and a tool do not agree, the test `tests/test_grammar_doc.py` fails. Since E7b (2026-10-23), the parser keeps each field of this file, and `tools/codewire_lint.py` gives the parse of §8 and the warnings of §9.

## 1. How to read the rules

The rules use a small form of EBNF:

| Sign | Meaning |
|---|---|
| `=` and `;` | the start and the end of a rule |
| `"text"` | these exact characters |
| `\|` | one of the two sides |
| `[ x ]` | `x` is optional |
| `{ x }` | `x` zero or more times |
| `( x )` | a group |
| `NL` | the end of a line |
| `(* … *)` | a note, not part of the rule |

The text is line by line. A rule never continues on the next line of the text, except where it shows `NL`. Use one space between two parts where the rule shows one space. A tab is not a space.

Each example in this file is a complete small graph in a `code-wire` block. The test reads each one with the parser of `codewire_extract.py`.

## 2. The file

```text
graph      = { free-line } { section } ;
free-line  = ? any line before the first section, for example the title "# …" and prose ? ;
section    = "## " title NL { block | edge-item | note-block | blank } ;
title      = "Nodes" | "Entities" | "Edges" | "Boundary" | "Routes" | "Findings" ;
block      = first-line NL { field-line } ;    (* a blank line ends the block *)
blank      = NL ;
note-block = ( "### " | ">" ) ? text ? NL { ? text ? NL } ;
```

- Write the sections in this order. Each section is optional, but a graph has at least `## Nodes`.
- A blank line separates two blocks.
- A block that starts with `###` or `>` is a note for people. The parser skips it.
- A section with a different title is not part of the graph (warning G1, §9).

## 3. Nodes

```text
node        = node-name NL { node-field NL } ;
node-name   = ? text with no ":", that does not start with "[", "#" or ">" ? ;
node-field  = key ":" [ " " value ] ;
key         = "req" | "in" | "out" | "func" | "module" | "examples"
            | "modify" | "inner" | "open" | "contract" | "volatile" | "oracle" ;
```

A node name is the name of the function, or `Class.method` for a method. The dot shows a method. A name can have spaces (`Read file`), but a name with no spaces is easier to use in `when:` (§5).

| Field | Required | Times | Value |
|---|---|---|---|
| `req:` | yes | 1 | `req-value` |
| `in:` | yes | 1 | `in-value`; it can be empty |
| `out:` | yes | 1 | `out-value` |
| `func:` | yes | 1 | prose, one paragraph |
| `module:` | yes | 1 | a path from the root folder of the repository, with no line number |
| `examples:` | yes | 1 or more | `example` |
| `modify:` | no | 1 | `modify-value` |
| `inner:` | if the node is a subsystem | 1 | `name-list` |
| `open:` | if a type is `Any` or a generic type with no parameters | 1 | prose: the data and the reason |
| `contract:` | no | 1 | prose: preconditions, postconditions or invariants |
| `volatile:` | no | 1 | `name-list` of values that change in each run: an input, an output name or `out`, with fields after dots |
| `oracle:` | no | 1 or more | prose: a source of truth outside the code and the graph |

A different key is not part of the graph (warning G2). A key two times in one node is warning G3, except `examples:` and `oracle:`.

### 3.1 Values

```text
req-value    = "to trace" | req-id { ", " req-id } ;
req-id       = ? a word such as R-1, US-032, LLR-036.3 or ADR-2 ? ;

in-value     = [ decl { "; " decl } ] ;       (* empty: the function has no parameter *)
decl         = [ "(Callable) " ] type " " name [ " = " default ] ;
name         = ? one word: letters, digits and "_" ? ;
default      = ? the default value, as in the code ? ;

out-value    = "None" | decl | "tuple(" decl { ", " decl } ")" ;

type         = union | func-type | "(" func-type ")?" ;
func-type    = [ union ] "->" union ;         (* "->datetime": a function with no argument *)
union        = optional { " | " optional } ;
optional     = base [ "?" ] ;                 (* X? : the value can be missing *)
base         = word [ "[" type { ", " type } "]" ] ;
word         = ? letters, digits, "_" and "." ? ;

modify-value = target [ " (" assign ")" ] { "; " target [ " (" assign ")" ] } ;
target       = entity-ref | name { "." name | "[]" } ;   (* an entity, or an input of the node *)
assign       = "replace" | "clear" | "append" ;

name-list    = name-or-node { ", " name-or-node } ;
example      = "(" ( marker | source { ", " part } ) ")" " " ? the thread line ? ;
source       = ? a test id such as T-5 or AT-036a, or a data case such as case_03 ? ;
part         = marker | "root " code-name | step ;
step         = ? a step of the thread, such as U2.4 or t1a ? ;
marker       = "synthetic" | "inferred" ;
code-name    = ? the qualname of a function in the code, such as LogApp.on_log_open ? ;
```

The parser splits `in:` at each `;` and `tuple(…)` at each `,` that is not inside brackets. Thus `dict[str, int] counts` is one input.

Three rules for `in:`:
1. **All the parameters**, also the ones with a default value (`str path = "logs/alarms.txt"`).
2. **An empty `in:`** for a function with no parameter. Do not write `in: None`: the tools read `None` as an input with the name `None`.
3. **`self`.** Write `Class self` only when the node uses data of its object that no entity declares. When that data is a `[Data: Class.attribute]` entity, the edges of the entity show the use, and `in:` has no `self`.

The thread line of `examples:` is prose with literal anchors. `Metodologia.md` §3.1 gives its rules, and rule C16 checks it.

`expect none` after the arrow says that the node has no call in that step (UI MF-6): `(U1, U1.6) an empty input → expect none`. C16 checks it in the event log, so the line needs a step. The log keeps a mark for each step, also for a step in which no node runs.

`volatile:` names the values of a node that change in each run. Examples are a time, or a key made from the address of an object. An item starts with an input, an output name or `out`; fields follow after dots: `out.mac_cache_key`. For an object, a field is a field of that object. The recorder keeps the value in the event, but the hash does not use it. Thus a diff of two runs does not stop at it.

A `volatile:` item that does not start with an input, an output or `out` is warning G10. `CW_VOLATILE` stays for a pattern that can be in any value, such as a temp folder.

`oracle:` names a source of truth outside the code and the graph: a standard, a section of a README, a file of examples. `req:` names only the ids of the project (data MF-10), so an outside source goes here. A node can have more than one `oracle:` line. An empty `oracle:` line is warning G11.

`root` names the entry point that started the recorded call: the root of the event in the event log. With a root, C16 compares the line only with the calls of that root. Thus a line that names the wrong entry point fails. With no root, C16 compares the line with each call of the node, as before.

Example:

```code-wire
## Nodes

count_kinds
req: R-6
in: list[str] lines
out: dict[str, int] counts
func: counts the lines of each kind
examples: (T-5) lines (2 of 3) "A 10:02 disk full" → counts "A": `1`
module: logtool/report.py

LogStore.clear
req: R-10
in:
out: None
func: empties the stack A
modify: [Data: LogStore.stack_a] (clear)
examples: (T-8) → None; [Data: LogStore.stack_a] has `0` lines
module: logtool/store.py

write_alarms
req: R-12
in: list[str] alarms; str path = "logs/alarms.txt"
out: int count
func: writes the alarm lines to a file and gives the number of lines
modify: [I/O: alarm file] (replace)
examples: (T-8) alarms (1 of 1) "A 10:02 disk full" → count `1`; [I/O: alarm file] has "A 10:02 disk full"
module: logtool/store.py
volatile: path
oracle: README.md, section "Alarm file": one alarm on each line
```

## 4. Entities

```text
entity      = entity-ref NL { entity-field NL } ;
entity-ref  = "[" kind ": " entity-name "]" ;
kind        = "Data" | "I/O" | "Interface" | "Database" | "API" | "Outside" | ? a kind that the project declares ? ;
entity-name = ? text with no "]" ? ;
entity-field = "in: " type | "desc: " ? prose ? | "sequence:" NL { sequence-line } | offer ;
offer       = "offers: " [ "(" source { ", " part } ") " ] '"' ? control ? '"' " → " node-name ;
sequence-line = "  " event ": " step { " → " step } NL ;
event       = name ;
step        = node-name [ " wins" ] [ " (!)" ] [ " (" ? prose ? ")" ] ;
```

`offers:` is only for an `[Interface]` entity. It names a control that the screen shows (a key, a button, a line of help) and the node that the control must run. An entity can have more than one `offers:` line. An example line is one run (may); an offer is for every run (must). With a source, C16 checks that the node ran in that step. An offer that is not of this form, that is not on an `[Interface]` entity, or whose node is not in `## Nodes`, is warning G9.

`sequence:` is only for a `[Data]` entity with more than one writer. Each line under it starts with two spaces. `wins` marks the write that stays at the end of the event. `(!)` marks a read before that write. `[Outside: …]` items do not go in `## Entities`: `## Boundary` declares them (§6).

Example:

```code-wire
## Nodes

LogStore.push_line
req: R-3
in: str line
out: None
func: puts a line of kind A on the stack A
modify: [Data: LogStore.stack_a] (append)
examples: (T-8) line (2 of 3) "A 10:02 disk full" → None; [Data: LogStore.stack_a] gets "A 10:02 disk full" (1 of 1)
module: logtool/store.py

## Entities

[Data: LogStore.stack_a]
in: list[str]
desc: the lines of kind A that the tool keeps
sequence:
  logOpen: LogStore.clear → LogStore.push_line wins → write_alarms
  reload: write_alarms (!) → LogStore.load wins

[Interface: help line]
desc: the line of keys under the log view
offers: (T-8, step 2) "a Add line" → LogStore.push_line
```

## 5. Edges

```text
edge-item   = edge NL [ when-line ] ;
edge        = end " ──▶ " [ quantifier " " ] end ;
end         = entity-ref [ "." field ] | node-name [ "." port ] ;
field       = name { "." name } ;
port        = name { "." name | "[]" } ;
quantifier  = "[1→N]" ;
when-line   = "when: " condition NL ;
condition   = node-name "." port [ " " ? prose ? ] | ? prose ? ;
```

The arrow is the three characters `──▶` (two U+2500 and one U+25B6). An end is an entity, a node with a port, or a node with no port:

| Form | Meaning (`Metodologia.md` §3.3) |
|---|---|
| `A.out ──▶ B.in` | the output `out` of `A` feeds the input `in` of `B` |
| `A ──▶ B.in` | caller edge: `A` computes `in` in its body and calls `B` |
| `A.out ──▶ B` | return edge: `B` called `A`, and uses `out` in its body |
| `A ──▶ B` | a call, with no value; C15 reads it |
| `[Kind: x] ──▶ B.in` or `A ──▶ [Kind: x]` | a read from an entity, or a write to it |
| `[Kind: x].f ──▶ B` or `A ──▶ [Kind: x].f` | a read of the field `f` of an entity, or a write to it |

`[1→N]` comes before the target: the target runs one time for each item.

A `when:` line belongs to the edge on the line before it. **The output comes first**: `when: has_alarm.alarm is False`, not `when: not has_alarm.alarm`. The tools find the output at the start of the condition. The rest of the line is prose. A condition with no output is prose only, for example `when: primary_file is None`.

A field names the part of an entity that an edge reads or writes (data MF-8). Two readers of two fields of one entity are two sources of truth. CW-D-7 came from such a pair: the plan reads `ranges` of the loaded file, and the writer reads `mem_map`. The parser keeps the entity and the field apart, so the checks of the entity (C4, C10) still see the entity. For a UI graph, declare the focus and the screen stack as entities: `[Data: App.focused]` and `[Data: App.screen_stack]` (UI MF-4).

An end that is not a node, a node port or an entity is warning G4. A field that is not a name is warning G12. A `when:` line with no edge before it is warning G5.

Example:

```code-wire
## Nodes

count_kinds
req: R-6
in: list[str] lines
out: dict[str, int] counts
func: counts the lines of each kind
examples: (T-5) lines (2 of 3) "A 10:02 disk full" → counts "A": `1`
module: logtool/report.py

has_alarm
req: R-7
in: dict[str, int] counts
out: bool alarm
func: tells if the log has an entry of kind A
examples: (T-5) counts "A": `1` → alarm True
module: logtool/report.py

summary_text
req: R-7
in: dict[str, int] counts
out: str text
func: writes the count of each kind
examples: (T-6) counts "B": `2` → text "B=2"
module: logtool/report.py

## Edges

count_kinds.counts ──▶ has_alarm.counts
count_kinds.counts ──▶ summary_text.counts
[Data: Settings].alarm_kind ──▶ has_alarm
when: has_alarm.alarm is False
```

## 6. Boundary

```text
boundary-line = edge NL | discarded NL ;
discarded     = "discarded: " node-name "." port " — " ? the reason ? ;
```

An edge in `## Boundary` has an `[Outside: name]` item at one end. A `discarded:` line names an output that nothing uses, and its reason. The separator is ` — ` (U+2014); the parser also reads ` - `.

Example:

```code-wire
## Nodes

LogStore.clear
req: R-10
in:
out: None
func: empties the stack A
examples: (T-8) → None
module: logtool/store.py

write_alarms
req: R-12
in: list[str] alarms; str path = "logs/alarms.txt"
out: int count
func: writes the alarm lines to a file and gives the number of lines
examples: (T-8) alarms (1 of 1) "A 10:02 disk full" → count `1`
module: logtool/store.py

## Boundary

[Outside: logOpen event] ──▶ LogStore.clear
discarded: write_alarms.count — the two events do not show the count
```

### 6.1 Routes

```text
routes-section = "## Routes" NL { route NL } ;
route          = "route: " ? name ? NL "entry: " entry { ", " entry } NL [ "desc: " ? prose ? NL ] ;
entry          = node-name | entity-ref | code-name ;
```

A route is one entry point of the app and the paths from it. The entry point can be a key, a button, a handler or the start of the app. `entry:` names the entry points. An entry is a node, an `[Outside: …]` item of `## Boundary`, or a function of the code. That function is the root of an event in the event log. The text does not list the nodes of a route: a tool derives them from the entries and the edges.

A route with no `entry:`, or an entry of a different form, is warning G8.

Example:

```code-wire
## Nodes

LogStore.clear
req: R-10
in:
out: None
func: empties the stack A
examples: (T-8, open, root LogApp.on_log_open) → None
module: logtool/store.py

## Boundary

[Outside: logOpen event] ──▶ LogStore.clear

## Routes

route: Open a log
entry: [Outside: logOpen event], LogApp.on_log_open
desc: the user opens a log file, and the tool empties the stack A first
```

## 7. Findings

```text
finding      = "finding " finding-id " " ? title ? NL { finding-field NL } ;
finding-id   = ? a word such as H-1 or HP-1 ? ;
finding-field = "anchor: " anchor | fkey ": " ? prose ? ;
anchor       = end | edge ;
fkey         = "seen" | "cause" | "effect" | "decision" ;
```

| Field | Required | Value |
|---|---|---|
| `anchor:` | yes | the node, port, entity or edge that the finding is about |
| `seen:` | yes | what a run or a review showed; start with the source in parentheses, as in `examples:` |
| `cause:` | no | why it occurs, with the place in the code |
| `effect:` | no | what goes wrong for the user or the next node |
| `decision:` | no | what the graph does about it: a change, or no change and the reason |

A finding is not part of the contract (`Metodologia.md` §8). An anchor that is not a node, a port, an entity or an edge of the graph is warning G6. A different field is warning G2.

Example:

```code-wire
## Nodes

LogStore.load
req: R-11
in: list[str] lines
out: None
func: puts all the lines of kind A on the stack A, in place of the old lines
modify: [Data: LogStore.stack_a] (replace)
examples: (T-9) lines (1 of 2) "A 11:00 fan stop" → None; [Data: LogStore.stack_a] has "A 11:00 fan stop" (1 of 2)
module: logtool/store.py

## Entities

[Data: LogStore.stack_a]
in: list[str]
desc: the lines of kind A that the tool keeps

## Findings

finding H-1 the alarm file keeps the old alarms after a reload
anchor: [Data: LogStore.stack_a]
seen: (T-9) the alarm file has "A 10:02 disk full", not the two new lines
cause: in the event reload, write_alarms reads the stack before LogStore.load writes it
effect: the alarm file shows the alarms of the old log until the next event
decision: no change to the graph; the order of the event reload changes in the code
```

## 8. What a parse gives

A tool that reads a graph gives one JSON object with these keys. The types of the code are Python types: the parser changes `X?` to `Optional[X]` and `A->B` to `Callable[[A], B]`.

| Key | Content of each item |
|---|---|
| `nodes` | `name`; `reqs` (a list of ids, `[]` for `to trace`); `in` (a list of `decl`); `out` (`type`, `names`, `raw`); `func`; `module`; `examples` (a list of lines); `modify` (a list of `target`, `assign`); `inner`; `open`; `contract`; `volatile` (a list of items); `oracle` (a list of lines) |
| `decl` | `kind` (`value`, `callable`, `self` or `untyped`); `type`; `name`; `default` |
| `entities` | `name` (the full `[Kind: name]`); `kind`; `in`; `desc`; `sequence` (a list of `event` and `steps`; each step has `node`, `wins` and `early`); `offers` (a list of `source`, `control` and `node`) |
| `edges` | `src` and `dst` (each with `node`, `port`, `entity` and `field`); `quantifier`; `when`; `boundary` (true in `## Boundary`); `raw` |
| `discarded` | `port`; `reason` |
| `routes` | `name`; `entries` (a list of names); `desc` |
| `findings` | `id`; `title`; `anchor`; `seen`; `cause`; `effect`; `decision` |
| `warnings` | `code` (§9); `line` (the line number in the file); `text` |

A key with no value in the text is `null`, or `[]` for a list.

## 9. Warnings

A warning does not stop a tool. It tells that a line is not part of the graph, or that a reference has no target. The tools skip that line. `codewire_lint.py` gives exit code 1 only for G7, or for a text with no node: then it cannot read a block.

| Code | The text has | Example |
|---|---|---|
| G1 | a section with a different title | `## Notes` |
| G2 | a field with a different key in a node, an entity or a finding | `fucn: counts the lines` |
| G3 | the same key two times in one node (not `examples:`) | two `out:` lines |
| G4 | an edge end that is not a node, a port of a node or an entity | `count_kind.counts ──▶ has_alarm.counts` |
| G5 | a `when:` line with no edge before it | `when:` as the first line of `## Edges` |
| G6 | a finding anchor that is not in the graph | `anchor: LogStore.reload` |
| G7 | a block that the parser cannot read: in `## Nodes`, no name line, or no `in:` and no `out:`; in `## Findings`, no `finding` line | a name line and a `func:` line only |
| G8 | a route with no `entry:`, or an entry that is not a node, an `[Outside: …]` item of `## Boundary` or a code name | `entry: [Data: LogStore.stack_a]` |
| G9 | an `offers:` line of another form, on an entity that is not `[Interface]`, or with a node that is not in `## Nodes` | `offers: "a" LogStore.push_line` |
| G10 | a `volatile:` item that does not start with an input, an output name or `out` | `volatile: started` on a node with no input `started` |
| G11 | an `oracle:` line with no source | `oracle:` |
| G12 | an end with an entity and then text that is not `.` and a name | `[Data: App.view] ranges ──▶ plan` |
