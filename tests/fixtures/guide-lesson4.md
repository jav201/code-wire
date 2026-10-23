# Lesson 4 graph (guide test)

## Nodes

make_report
req: R-7
in: str path
out: str report
func: reads the log and writes the report line
examples: (T-5) path "logs/app.log" → report "ALARM: 1 entries of kind A"
module: logtool/report.py
inner: read_lines, count_kinds, has_alarm, alarm_text, summary_text

read_lines
req: R-2
in: str path
out: list[str] lines
func: reads the log file: one item for each line
examples: (T-5) path "logs/app.log" → lines (2 of 3) "A 10:02 disk full"
module: logtool/report.py

count_kinds
req: R-6
in: list[str] lines
out: dict[str, int] counts
func: counts the lines of each kind
examples: (T-5) lines (2 of 3) "A 10:02 disk full" → counts "A": `1`
module: logtool/report.py

entry_kind
req: R-3
in: str line
out: str kind
func: gives the kind of a log entry: the first word of the line
examples: (T-1) line "A 10:02 disk full" → kind "A"
module: logtool/classify.py

has_alarm
req: R-7
in: dict[str, int] counts
out: bool alarm
func: tells if the log has an entry of kind A
examples: (T-5) counts "A": `1` → alarm True
module: logtool/report.py

alarm_text
req: R-7
in: dict[str, int] counts
out: str text
func: writes the alarm line
examples: (T-5) counts "A": `1` → text "ALARM: 1 entries of kind A"
module: logtool/report.py

summary_text
req: R-7
in: dict[str, int] counts
out: str text
func: writes the count of each kind
examples: (T-6) counts "B": `2` → text "B=2"
module: logtool/report.py

## Edges

make_report ──▶ read_lines.path
read_lines.lines ──▶ count_kinds.lines
count_kinds ──▶ entry_kind.line
entry_kind.kind ──▶ count_kinds
count_kinds.counts ──▶ has_alarm.counts
count_kinds.counts ──▶ alarm_text.counts
when: has_alarm.alarm
count_kinds.counts ──▶ summary_text.counts
when: has_alarm.alarm is False
alarm_text.text ──▶ make_report
summary_text.text ──▶ make_report

## Boundary

[Outside: command line] ──▶ make_report.path
make_report.report ──▶ [Outside: screen]
