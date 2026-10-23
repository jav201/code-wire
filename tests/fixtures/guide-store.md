# Graph: the alarm stack of the log tool (a flow slice)

## Nodes

read_lines
req: R-2
in: str path
out: list[str] lines
func: reads the log file: one item for each line
examples: (T-8) path "logs/app.log" → lines (2 of 3) "A 10:02 disk full"
module: logtool/report.py

entry_kind
req: R-3
in: str line
out: str kind
func: gives the kind of a log entry: the first word of the line
examples: (T-1) line "A 10:02 disk full" → kind "A"
module: logtool/classify.py

LogStore.push_line
req: R-3
in: str line
out: None
func: puts a line of kind A on the stack A
modify: [Data: LogStore.stack_a] (append)
examples: (T-8) line (2 of 3) "A 10:02 disk full" → None; [Data: LogStore.stack_a] gets "A 10:02 disk full" (1 of 1)
module: logtool/store.py

LogStore.clear
req: R-10
in:
out: None
func: empties the stack A
modify: [Data: LogStore.stack_a] (clear)
examples: (T-8) → None; [Data: LogStore.stack_a] has `0` lines
module: logtool/store.py

LogStore.load
req: R-11
in: list[str] lines
out: None
func: puts all the lines of kind A on the stack A, in place of the old lines
modify: [Data: LogStore.stack_a] (replace)
examples: (T-9) lines (1 of 2) "A 11:00 fan stop" → None; [Data: LogStore.stack_a] has "A 11:00 fan stop" (1 of 2)
module: logtool/store.py

write_alarms
req: R-12
in: list[str] alarms; str path = "logs/alarms.txt"
out: int count
func: writes the alarm lines to a file and gives the number of lines
modify: [I/O: alarm file] (replace)
examples: (T-8) alarms (1 of 1) "A 10:02 disk full" → count `1`; [I/O: alarm file] has "A 10:02 disk full"
module: logtool/store.py

## Entities

[I/O: log file]
in: str
desc: the log that the tool reads, one entry for each line

[Data: LogStore.stack_a]
in: list[str]
desc: the lines of kind A that the tool keeps
sequence:
  logOpen: LogStore.clear → LogStore.push_line wins → write_alarms
  reload: write_alarms (!) → LogStore.load wins

[I/O: alarm file]
in: str
desc: the alarm lines, one for each line

## Edges

[I/O: log file] ──▶ read_lines.path
read_lines.lines ──▶ [1→N] LogStore.push_line.line
read_lines.lines ──▶ LogStore.load.lines
LogStore.push_line ──▶ entry_kind.line
entry_kind.kind ──▶ LogStore.push_line
LogStore.load ──▶ entry_kind.line
entry_kind.kind ──▶ LogStore.load
[Data: LogStore.stack_a] ──▶ write_alarms.alarms

## Boundary

[Outside: logOpen event] ──▶ LogStore.clear
discarded: write_alarms.count — the two events do not show the count

## Findings

finding H-1 the alarm file keeps the old alarms after a reload
anchor: [Data: LogStore.stack_a]
seen: (T-9) the alarm file has "A 10:02 disk full", not the two new lines
cause: in the event reload, write_alarms reads the stack before LogStore.load writes it
effect: the alarm file shows the alarms of the old log until the next event
