# Code-Wire — the method

> v3.2 (2026-11-12): the tools read what authors write. In one run, 60 of 78 extractor findings were unread notations. Removed: the stub of §5, the extractor as a condition of "Done", `findings=` in the lint line. History: git.

## 1. The idea

Describe a part of a program as a set of black-box functions. For each function, write its contract (typed inputs, one output) and at least one concrete example: the value that goes in and the value that must come out, taken from the requirement or another source of truth, not from the code. Then run the code and see if the example holds.

The examples are where the method finds problems. A concrete expected value makes you check what the code really does. A defect counts only when a run shows it.

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
- `examples:` is the thread: one real item followed through the flow. Name its source (a test id or a probe), and write the values that the line commits to as anchors: `0x…`, text in backticks or quotes, a number, `True`, `False` or `None` in backticks. The rest of the line is prose. `Notation-Grammar.md` §3.1 says how an anchor matches.

**Optional parts.** Use one only when the case needs it. Each one comes from a real defect:

| Part | Use it for | The case that asked for it |
|---|---|---|
| `modify:` and `[Data: …]` entities | a function that changes shared state | the state that a handler with no output writes (a data-flow audit) |
| `sequence:` with `wins` and `(!)` | the order of writes and reads in one event | a read before the write that wins (H-1; the focus defect, a UI audit) |
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

## 4. Find, prove, confirm

- **Find.** Two things find defects: an example written from the requirement (or the `oracle:`), and the list of the real callers in the extractor report, also the callers outside the slice ("Top-level sites"). In a flow test, three defects came from examples and one from a caller in another file.
- **Prove.** A defect counts only with a run that shows it: a regression test that fails before the fix and passes after, or a C16 drift.
- **Confirm and keep.** C16 (`codewire_examples.py`) checks many example lines against a recording at once, and keeps the record. With a root, only the calls from that root count; `expect none` and an offer check one step. The report starts with the lines that no recording backs. C16 exits 1 when a line with a recording does not hold (drift, no def, not run, no anchor); a line with no recording does not fail it, because a test can be its proof.
- **The other two tools:** the extractor (`codewire_extract.py`) binds each mark `# node: name` to its def, checks the contract (inputs, types, defaults, output, module), and lists the real calls; `--path` keeps it to one slice. It exits 1 on a drift; its report is a list for the integrator. The next design starts from this graph, so bring it up to date. `--layered` (also C16): a later graph replaces a node of the same module and name. The lint (`codewire_lint.py`) lists each graph line that the parser does not read: an error.

## 5. On a change, and in an audit

- **A change.** Before the code: write the nodes that change, with examples from the requirement; the prototype is the graph only. After the code: run the examples (a test or C16); to check the graph, `codewire_marks.py` marks a throwaway clone and the extractor runs there. Done = each example holds.
- **An audit of existing code.** (1) For each function, find what it must do: a requirement, a spec, a document. (2) Write one example from that, not from the code. (3) Mark the functions and run the extractor; read the callers, also outside the slice. (4) Run each example (a probe or a test). (5) Each example that does not hold is a candidate; it is a finding when a regression test shows it. Done = each finding has a test that failed before the fix and passes after.
- **The review.** A person reads the summary (the findings with their tests, what changed), not the graph.

## 6. Rules for the method itself

1. A new field or check enters only with the real defect that it finds, or would have found, in a named run. With no such defect, it is an experiment on a branch.
2. Nothing is documented or taught before someone other than its author used it on a real case.
3. A change to the method says what it removes, not only what it adds.

## 7. What the method is not

- Not a design notation for drawings. The text is the source.
- Not a gate of style rules. A graph with clean rules can still be wrong; only the checked examples tell.
- Not for every change. Use it where the flow is long enough that a reader cannot hold it.
