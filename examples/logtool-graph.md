# Example graph: from a log file path to two log stacks

This is the example of `docs/Metodologia.md` §10, in format B (v2.5). There is no code behind it, so the `module:` paths and the examples are synthetic.

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
