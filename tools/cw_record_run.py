"""Record a script, not only a pytest run: the probes of an audit are scripts.

    python tools/cw_record_run.py --graph g.md [--graph …] [--path DIR] [--root DIR] [--adapters textual]
        [--step-regex REGEX] [--run ID] [--events ev.jsonl] [--trace trace.json] script.py [args …]

The nodes of the graphs are wrapped as in the pytest plugin, then the script runs as `__main__`.
Steps: the script can call `codewire_events.step("U1.3")`, or `--step-regex` reads its output: each
printed line that matches sets the step to group 1 (for example `^== (U\\d+\\.\\d+)`).
The event log and the trace are written also when the script fails; the exit code is the script's.
"""
import argparse
import os
import re
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codewire_events as events  # noqa: E402
import cw_record_plugin as rec  # noqa: E402


class StepReader:
    """A stream that passes the output on and sets the step from each line that matches."""

    def __init__(self, stream, rx):
        self.stream, self.rx, self.buf = stream, rx, ""

    def write(self, text):
        self.buf += text
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            m = self.rx.search(line)
            if m:
                events.step(m.group(1))
        return self.stream.write(text)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--graph", required=True, action="append")
    ap.add_argument("--path", action="append", default=[], help="a folder to put on sys.path (the code under test)")
    ap.add_argument("--root", help="folder of the project code (entry points); default: the first --path, else cwd")
    ap.add_argument("--adapters", default="", help="framework adapters, separated by commas (textual)")
    ap.add_argument("--step-regex", help="a printed line that matches sets the step to group 1")
    ap.add_argument("--run", default=None, help="run id in each event (default: the script name)")
    ap.add_argument("--events", default="cw-events.jsonl")
    ap.add_argument("--trace", default="cw-trace.json")
    ap.add_argument("script")
    ap.add_argument("args", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)

    # the script can change the working folder (the probes do), so fix the output paths first
    a.events, a.trace = os.path.abspath(a.events), os.path.abspath(a.trace)
    for p in reversed(a.path):
        sys.path.insert(0, str(Path(p).resolve()))
    sys.path.insert(0, str(Path(a.script).resolve().parent))
    root = a.root or (a.path[0] if a.path else os.getcwd())
    events.ROOT_DIR[0] = os.path.normcase(os.path.abspath(root))
    events.RUN = a.run or Path(a.script).stem
    rec.install(a.graph, [n.strip() for n in a.adapters.split(",") if n.strip()])
    if a.step_regex:
        # Textual sends a print of a running app to sys.__stdout__, so read that stream too
        sys.stdout = StepReader(sys.stdout, re.compile(a.step_regex))
        if sys.__stdout__ is not None and sys.__stdout__ is not sys.stdout.stream:
            sys.__stdout__ = StepReader(sys.__stdout__, sys.stdout.rx)
        else:
            sys.__stdout__ = sys.stdout

    sys.argv = [a.script] + a.args
    code = 0
    try:
        runpy.run_path(a.script, run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException:
        code = 1
        raise
    finally:
        for name in ("stdout", "__stdout__"):
            if isinstance(getattr(sys, name), StepReader):
                setattr(sys, name, getattr(sys, name).stream)
        rec.save(a.events, a.trace)
        print(f"cw_record_run: {len(events.EVENTS)} events -> {a.events}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
