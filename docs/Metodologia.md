# Code-Wire — the method

> v3 (2026-10-25): the core only. A reduction review of five real uses (app first-use, two app audits, second-project batches 006 and 009) showed that every real finding came from one thing: a concrete example for each function, checked against a recording of the real code. What found nothing left the method. The history is in git.

## 1. The idea

Describe a part of a program as a set of black-box functions. For each function, write its contract (typed inputs, one output) and at least one concrete example: a real value that goes in and the value that comes out. Then record the real code while it runs, and check each example against the recording.

The examples are where the method finds problems. Writing one concrete line for each function makes you look at what the code really does. The recording makes the line a fact, not a guess.

**When not to use it:** for a small change that one reader can see whole (one script, a few functions). There it costs more than it finds.

## 2. The graph text

The graph is a text file. It is the source; a drawing is only a help for the eye. `Notation-Grammar.md` gives the exact form of each line.

**A node** is one function or method:

```
write_alarms
req: R-12
in: list[str] alarms; str path = "logs/alarms.txt"
out: int count
func: writes the alarm lines to a file and gives the number of lines
module: logtool/store.py
examples: (T-8) alarms (1 of 1) "A 10:02 disk full" → count `1`
```

- `in:` lists every parameter with its type, also the ones with a default. `out:` is one output.
- `examples:` is the thread: one real item followed through the flow. Name its source (a test id or a probe), and write the values that the line commits to as anchors: `0x…`, text in backticks or quotes, a number in backticks. The rest of the line is prose.
- A line that no recording backs yet gets the marker `unrecorded`: `(T-8, unrecorded)`.

**Optional parts.** Use one only when the case needs it. Each one comes from a real defect:

| Part | Use it for | The case that asked for it |
|---|---|---|
| `modify:` and `[Data: …]` entities | a function that changes shared state | the state that a handler with no output writes (app data audit) |
| `sequence:` with `wins` and `(!)` | the order of writes and reads in one event | a read before the write that wins (H-1; the focus defect, app UI audit) |
| `[Outside: key]` edge with `when:` | a key that runs a function under a condition | the focus that takes the keys (CW-U-2) |
| `[Data: X].field` edge | two readers of two fields of one entity | CW-D-7: the plan reads one field, the writer another |
| `root X` in the source of a line | the entry point that must start the call | a line that passed only because a test called the function directly (CW-U-1) |
| `→ expect none` | "nothing happens in this step" | an empty input that gives no feedback (CW-U-13) |
| `offers:` on an `[Interface]` entity | a control that the screen offers, and the function that it must run | keys that the key bar offers and that do nothing (CW-U-2) |
| `volatile:` | values that change in each run | keys made from object ids in the load payload |
| `oracle:` | a source of truth outside the code | the decisive oracles were a spec, a README, an example file |
| `## Findings` | what you found and decided | — |

An edge between two functions (`a.out ──▶ b.in`) is optional. The extractor lists the real calls from the code.

## 3. The recording

The recorder wraps each function of the graph while the real code runs, and writes an event log:

- **Under pytest:** `cw_record_plugin.py`. **For a probe script:** `cw_record_run.py`; a printed line such as `== U2.4` starts a step.
- **Each event** has the step, the **root** (the entry point that started the call, or `harness` when a test called the function directly), the parent, the inputs, the output, and the values after the call: the inputs that the function changes, and the `[Data: Class.attribute]` of its own object.
- **The hash** of an event leaves out what changes from run to run: temp folders, object addresses, the project folder (`<ROOT>`), and the `volatile:` items. So a diff of two runs stops at a real change.
- **A Textual app:** `CW_ADAPTERS=textual` carries the root across messages, dialogs and workers.
- **Views of a log:** `codewire_events.py report` gives the examples of each root, the paths and a root × function matrix; `… diff` gives the first step where two logs differ.

A write that a worker makes later is not in the values after the call.

## 4. The checks

There are three, and only three:

1. **C16, the examples check** (`codewire_examples.py`). Each example line holds when its anchors are in one recorded call of its function. With a root, only the calls from that root count. `expect none` holds when the function has no call in that step. An offer holds when its function ran in that step. The report starts with the number of lines that no recording backs.
2. **The extractor** (`codewire_extract.py`). Each mark `# node: name` binds to its def, and the contract of the graph matches the code: inputs, types, defaults, output, module. It lists the real calls between the functions. `--path` keeps it to one slice.
3. **The lint** (`codewire_lint.py`). It lists each line of the graph that the parser does not read. A tool would skip such a line with no word, so each one is an error.

## 5. Before and after the code

- **Before the code (plan):** write the nodes that the change adds or changes, with their example lines marked `unrecorded`. Write each new function as a stub with its mark. The plan says which nodes change.
- **After the code:** record the threads, then run C16 and the extractor. The change is done when C16 has no drift and no `unrecorded` line for the changed nodes, and the extractor has no drift. **No recording, no done.**
- **The review:** a person reads the summary (what changed, the findings, the number of lines with no recording), not the graph.

## 6. Rules for the method itself

1. A new field or check enters only with the real defect that it finds, or would have found, in a named run. With no such defect, it is an experiment on a branch.
2. Nothing is documented or taught before someone other than its author used it on a real case.
3. A change to the method says what it removes, not only what it adds.

## 7. What the method is not

- Not a design notation for drawings. The text is the source.
- Not a gate of style rules. A graph with clean rules can still be wrong; only the checked examples tell.
- Not for every change. Use it where the flow is long enough that a reader cannot hold it.
