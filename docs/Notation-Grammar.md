# Code-Wire — grammar of the graph text (format B)

> The full form of each line of a graph text. `Metodologia.md` gives the meaning of each part. The test `tests/test_grammar_doc.py` reads each example of this file with the parser, so this file and the tools agree.

## 1. How to read the rules

| Sign | Meaning |
|---|---|
| `=` and `;` | the start and the end of a rule |
| `"text"` | these exact characters |
| `\|` | one of the two sides |
| `[ x ]` | `x` is optional |
| `{ x }` | `x` zero or more times |
| `NL` | the end of a line |
| `(* … *)` | a note, not part of the rule |

The text is read line by line. A blank line ends a block.

## 2. The file

```text
graph      = { free-line } { section } ;
free-line  = ? any line before the first section: the title "# …", prose ? ;
section    = "## " title NL { block | edge-item | note-block | blank } ;
title      = "Nodes" | "Entities" | "Edges" | "Findings" ;
block      = first-line NL { field-line } ;
note-block = ( "### " | ">" ) ? text ? NL { ? text ? NL } ;
```

Each section is optional, but a graph has `## Nodes`. A block that starts with `###` or `>` is a note for people; the parser skips it. Any other line that the parser does not read is an error (§8).

## 3. Nodes

```text
node        = node-name NL { node-field NL } ;
node-name   = ? the qualname of the function or method: "f" or "Class.method" ? ;
node-field  = key ":" [ " " value ] ;
key         = "req" | "in" | "out" | "func" | "module" | "examples"
            | "modify" | "volatile" | "oracle" ;
```

| Field | Value |
|---|---|
| `req:` | the requirement ids, separated by `,`; `to trace` when there is none yet |
| `in:` | each parameter as `type name`, separated by `;`; also the ones with a default (`str path = "logs/a.txt"`). Empty for no parameter. `X?` is an optional type; `(Callable) A->B name` is a function as input; `Class self` only when the node uses data of its object that no entity names |
| `out:` | one output, `type name`; `tuple(A a, B b)` for more than one value; `None` when the node only changes state |
| `func:` | what the node does, in one or two lines |
| `module:` | the file, from the root of the repository |
| `examples:` | one line for each input → output pair; repeat the field for more lines (§3.1) |
| `modify:` | what the node changes, each with `(replace)`, `(clear)` or `(append)`: an entity `[Data: …]`, or an input of the node by name. Separate them with `;` |
| `volatile:` | the values that change in each run: an input, `out` or an output name, with fields after dots (`prepared.mac_cache_key`). The recorder keeps them in the event; the hash does not use them |
| `oracle:` | a source of truth outside the code: a standard, a README section, a file of examples. Repeat for more |

A key two times in one node is an error, except `examples:` and `oracle:`.

### 3.1 Example lines

```text
example = "(" source { ", " part } ")" " " ? the thread: prose with literal anchors ? ;
part    = step | "root " code-name | "unrecorded" ;
```

- The **source** is the thread: a test id or a probe (`T-8`, `U2`). The **step** names the step of a probe (`U2.4`).
- **Anchors** are what C16 compares with the recording: `0x…`, text in backticks, `"…"`, `«…»`, and a number in backticks (`` `6` ``). The rest of the line is prose.
- **`root X`** names the entry point that started the call. Then C16 compares the line only with the calls from that root.
- **`→ expect none`** after the arrow says that the node has no call in that step. It needs a step and an event log.
- **`unrecorded`** marks a line that no recording backs yet. C16 counts it and does not check it.

```code-wire
## Nodes

count_kinds
req: R-6
in: list[str] lines
out: dict[str, int] counts
func: counts the lines of each kind
module: logtool/report.py
examples: (T-5) lines (2 of 3) "A 10:02 disk full" → counts "A": `1`

write_alarms
req: R-12
in: list[str] alarms; str path = "logs/alarms.txt"
out: int count
func: writes the alarm lines to a file and gives the number of lines
module: logtool/store.py
modify: [I/O: alarm file] (replace)
examples: (T-8, root on_log_open) alarms (1 of 1) "A 10:02 disk full" → count `1`
examples: (P, P2) a log with no entry of kind A → expect none
volatile: path
oracle: README.md, section "Alarm file": one alarm on each line
```

## 4. Entities

```text
entity       = "[" kind ": " entity-name "]" NL { entity-field NL } ;
kind         = "Data" | "I/O" | "Interface" | "Outside" | ? a kind that the project names ? ;
entity-field = "in: " type | "desc: " ? prose ? | "sequence:" NL { sequence-line } | offer ;
sequence-line = "  " event ": " step { " → " step } NL ;
step         = node-name [ " wins" ] [ " (!)" ] [ " (" ? prose ? ")" ] ;
offer        = "offers: " [ "(" source { ", " part } ") " ] '"' ? control ? '"' " → " node-name ;
```

- An entity is where data is kept or used: a shared attribute, a file, a screen, an outside caller.
- `sequence:` gives the order of the writes and reads of one event. `wins` marks the write that stays; `(!)` marks a read before that write.
- `offers:` on an `[Interface]` entity names a control that the screen shows and the node that it must run. An example line tells what one run did; an offer tells what each press must do. With a source, C16 checks that the node ran in that step.
- For a UI, the focus and the screen stack are entities: `[Data: App.focused]`, `[Data: App.screen_stack]`.

```code-wire
## Nodes

LogStore.push_line
req: R-3
in: str line
out: None
func: puts a line of kind A on the stack A
module: logtool/store.py
modify: [Data: LogStore.stack_a] (append)
examples: (T-8) line (2 of 3) "A 10:02 disk full" → None; [Data: LogStore.stack_a] gets "A 10:02 disk full"

## Entities

[Data: LogStore.stack_a]
in: list[str]
desc: the lines of kind A that the tool keeps
sequence:
  logOpen: LogStore.clear → LogStore.push_line wins → write_alarms
  reload: write_alarms (!) → LogStore.load wins

[Interface: help line]
desc: the keys under the log view
offers: (T-8, step 2) "a Add line" → LogStore.push_line
```

## 5. Edges

```text
edge-item = edge NL [ "when: " ? condition ? NL ] ;
edge      = end " ──▶ " end ;
end       = entity-ref [ "." field ] | node-name [ "." port ] ;
field     = name { "." name } ;
```

The arrow is `──▶`. The edges that carry meaning are the reads and writes of an entity:

| Form | Meaning |
|---|---|
| `[Data: x] ──▶ b` | `b` reads the entity |
| `a ──▶ [Data: x]` | `a` writes the entity |
| `[Data: x].f ──▶ b` | `b` reads the field `f`. Two readers of two fields are two sources of truth |
| `[Outside: key] ──▶ b` + `when:` | a key press runs `b` under a condition, for example the focus |

An edge between two nodes (`a.out ──▶ b.in`) is optional. The extractor lists the real calls from the code.

```code-wire
## Nodes

has_alarm
req: R-7
in: dict[str, int] counts
out: bool alarm
func: tells if the log has an entry of kind A
module: logtool/report.py
examples: (T-5) counts "A": `1` → alarm True

## Entities

[Data: Settings]
desc: the settings that the user saves

## Edges

[Data: Settings].alarm_kind ──▶ has_alarm
[Outside: key a] ──▶ has_alarm
when: App.focused is the log view
```

## 6. Findings

```text
finding = "finding " id " " ? title ? NL { finding-field NL } ;
finding-field = fkey ": " ? prose ? ;
fkey    = "anchor" | "seen" | "cause" | "effect" | "decision" ;
```

A finding records a result of the work: what was seen, where, and what was decided. It is not part of the contract.

```code-wire
## Nodes

LogStore.load
req: R-11
in: list[str] lines
out: None
func: puts all the lines of kind A on the stack A, in place of the old lines
module: logtool/store.py
examples: (T-9) lines (1 of 2) "A 11:00 fan stop" → None

## Findings

finding H-1 the alarm file keeps the old alarms after a reload
anchor: LogStore.load
seen: (T-9) the alarm file has "A 10:02 disk full", not the two new lines
cause: in the event reload, write_alarms reads the stack before LogStore.load writes it
decision: the order of the event reload changes in the code
```

## 7. What a parse gives

`codewire_lint.py --json` writes one JSON object with these keys:

| Key | Content of each item |
|---|---|
| `nodes` | `name`; `reqs` (a list of ids, `[]` for `to trace`); `in` (a list of `decl`); `out` (`type`, `names`, `raw`); `func`; `module`; `examples` (a list of lines); `modify` (a list of `target`, `assign`); `volatile` (a list of items); `oracle` (a list of lines) |
| `decl` | `kind` (`value`, `callable`, `self` or `untyped`); `type`; `name`; `default` |
| `entities` | `name`; `kind`; `in`; `desc`; `sequence` (a list of `event` and `steps`); `offers` (a list of `source`, `control` and `node`) |
| `edges` | `src` and `dst` (each with `node`, `port`, `entity` and `field`); `when`; `raw` |
| `findings` | `id`; `title`; `anchor`; `seen`; `cause`; `effect`; `decision` |
| `unread` | `line`; `text` |

## 8. Lines that the parser does not read

A tool skips such a line with no word, and then a node can be lost from a recording. So each one is an error, and `codewire_lint.py` exits with code 1:

- a section with another title;
- a block with no name line, or a node with no `in:` and no `out:`;
- a field that is not in the lists above, or a key two times in one node;
- a `volatile:` item that does not start with an input, an output or `out`;
- an `offers:` line of another form;
- an entity end with text after `]` that is not `.` and a name;
- a `when:` line with no edge before it, or any other line in `## Edges`;
- a block in `## Findings` with no `finding` line.
