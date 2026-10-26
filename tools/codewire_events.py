"""Code-Wire event log: one event for each recorded call of a graph node.

The recorder (`cw_record_plugin.py`) calls `record()` for each call. An event holds the run, the test,
the step, the root (the entry point that started the call), the parent (the node that called it), the
literal inputs and output, and a hash of those values after the volatile parts are normalized.

    CW_ENTRY     regex for the name of an entry-point function (default `^(action_|on_)`)
    CW_ROOT      folder of the project code; only frames from files in it can be a root (default: cwd)
    CW_VOLATILE  more regexes for volatile text, separated by os.pathsep (temp folders and object
                 addresses are always volatile)
    CW_EVENTS    event log to write, one JSON object per line (default cw-events.jsonl)
    CW_RUN       run id written in each event (default `pytest`)

A call with no entry frame on the stack has the root `harness`: a test or a script called the node
directly, not through an entry point of the app. An adapter for a framework (`cw_textual.py`) carries
the root and the parent over a hand-off (a message, a callback, a worker) with `carry()` and `stamp()`.
"""
import functools
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path

HARNESS = "harness"
ENTRY = "ENTRY"
ENTRY_RX = re.compile(os.environ.get("CW_ENTRY", r"^(action_|on_)"))
ROOT_DIR = [os.path.normcase(os.path.abspath(os.environ.get("CW_ROOT", os.getcwd())))]
RUN = os.environ.get("CW_RUN", "pytest")
STEP = ["-"]
SEQ = [0]
EVENTS = []
EXTRAS = []   # adapters add f(event) to put more fields on each event (the screen channel)
_TL = threading.local()
_LOCK = threading.Lock()


def _volatile():
    sep = r"[\\/]+"   # `\`, `/`, and the doubled `\\` of a JSON string
    parts = re.split(r"[\\/]+", str(Path(tempfile.gettempdir()).resolve()))
    tmp_any = sep.join(re.escape(p) for p in parts if p)
    rx = [(tmp_any + sep + r"[^\\/'\"\s]+", "<TMP>"), (tmp_any, "<TMP>"), (r"0x[0-9A-Fa-f]{8,}", "<addr>")]
    rx += [(p, "<volatile>") for p in os.environ.get("CW_VOLATILE", "").split(os.pathsep) if p]
    return [(re.compile(p, re.I), t) for p, t in rx]


VOLATILE = _volatile()


def normalize(text):
    for rx, token in VOLATILE:
        text = rx.sub(token, text)
    return text


def event_hash(node, inputs, output, after=None):
    """The same values give the same hash in every run: temp folders and addresses do not count."""
    body = json.dumps([node, inputs, output, after], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(normalize(body).encode("utf-8")).hexdigest()[:10]


def _in_project(code):
    f = os.path.normcase(os.path.abspath(code.co_filename))
    return f.startswith(ROOT_DIR[0]) and "site-packages" not in f


def carry(fn, ctx):
    """Wrap `fn` so that the calls it makes have the root and parent `ctx`, also when it runs later
    or in another thread (a hand-off). The context lives in the frame of the wrapper."""
    @functools.wraps(fn)
    def _cw_run(*a, **k):
        cw_ctx = ctx  # noqa: F841 (read by origin() through the frame)
        return fn(*a, **k)
    return _cw_run


HANDOFF_CODE = carry(lambda: None, None).__code__


def stamp(obj, ctx):
    """Give `ctx` to an object that a hand-off carries (a message, a dialog screen)."""
    try:
        obj.__dict__["_cw_ctx"] = ctx
    except (AttributeError, TypeError):
        pass


def _stamp_of(values):
    for v in values:
        try:
            ctx = object.__getattribute__(v, "__dict__").get("_cw_ctx")
        except (AttributeError, TypeError):
            continue
        if ctx:
            return tuple(ctx)
    return None


def _stamped(frame):
    return _stamp_of(frame.f_locals.values())


def origin(frame):
    """(root, parent) of the code that runs in `frame`, or None for a harness.
    Walking out from `frame`, the first hand-off wrapper or stamped entry frame gives the context. Else
    the outermost entry frame of project code is the root, with the parent ENTRY."""
    best = None
    while frame is not None:
        code = frame.f_code
        if code is HANDOFF_CODE:
            ctx = frame.f_locals.get("cw_ctx")
            if ctx:
                return tuple(ctx)
        elif ENTRY_RX.search(code.co_name) and _in_project(code):
            ctx = _stamped(frame)
            if ctx:
                return tuple(ctx)
            best = (getattr(code, "co_qualname", code.co_name), ENTRY)
        frame = frame.f_back
    return best


def here(frame):
    """The context that a hand-off made now in `frame` must carry: (root, open node), or None."""
    stack = _open()
    if stack:
        return stack[-1]
    return origin(frame)


def _open():
    if not hasattr(_TL, "open"):
        _TL.open = []
    return _TL.open


def begin(node, frame, code=None, args=()):
    """Open a call of `node` that starts in `frame`; returns the event to give to `end()`.
    The root and the parent come from the first of: the open node; a stamp on an argument of the call
    (the dialog screen in `self`, a message); the stack (`origin`); the node itself when its function
    `code` is an entry point that the framework called; else `harness`."""
    stack = _open()
    if stack:
        root, parent = stack[-1]
    else:
        ctx = _stamp_of(args) or origin(frame)
        if ctx is None and code is not None and ENTRY_RX.search(code.co_name) and _in_project(code):
            ctx = (getattr(code, "co_qualname", code.co_name), ENTRY)
        root, parent = ctx or (HARNESS, HARNESS)
    with _LOCK:
        SEQ[0] += 1
        seq = SEQ[0]
    ev = {"run": RUN, "test": os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0], "step": STEP[0],
          "seq": seq, "root": root, "parent": parent, "node": node, "thread": threading.current_thread().name}
    stack.append((root, node))
    return ev


def end(ev, call=None):
    """Close the call. With `call`, copy the recorded values, hash them and keep the event; with no
    `call` (over the limit), only close it."""
    stack = _open()
    if stack:
        stack.pop()
    if call is None:
        return None
    for k in ("in", "out", "after", "files"):
        if k in call:
            ev[k] = call[k]
    ev["hash"] = event_hash(ev["node"], ev.get("in"), ev.get("out"), ev.get("after"))
    for extra in EXTRAS:
        extra(ev)
    with _LOCK:
        EVENTS.append(ev)
    return ev


def step(label):
    """Name the step of the run that the next events belong to (a script or a test can call it)."""
    STEP[0] = str(label)


def write(path=None, events=None, skipped=None):
    """Write the log: one JSON object per line. A first line {"meta": …} keeps the nodes that the
    recorder skipped (no code yet), which C16 needs to tell NEW nodes."""
    path = path or os.environ.get("CW_EVENTS", "cw-events.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"meta": {"run": RUN, "skipped": list(skipped or [])}}) + "\n")
        for ev in (EVENTS if events is None else events):
            f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
    return path


def read(path):
    """The events of a log, in call order (the meta line is not an event)."""
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted((r for r in rows if "meta" not in r), key=lambda e: (e.get("run", ""), e["seq"]))


def read_meta(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            return json.loads(line).get("meta", {})
    return {}


def trace_view(events, max_calls=3, skipped=()):
    """The old trace shape {node: [call, …]} that C16 reads, with at most `max_calls` calls for each
    (root, node) pair (None: all of them)."""
    trace, kept = {"_skipped": list(skipped)}, {}
    for ev in sorted(events, key=lambda e: e["seq"]):
        key = (ev["root"], ev["node"])
        if max_calls is not None and kept.get(key, 0) >= max_calls:
            continue
        kept[key] = kept.get(key, 0) + 1
        call = {"test": ev.get("test", ""), "root": ev["root"], "parent": ev["parent"], "step": ev.get("step")}
        call.update({k: ev[k] for k in ("in", "out", "after", "files") if k in ev})
        trace.setdefault(ev["node"], []).append(call)
    return trace


# ---- views (A2d): what the log shows, by root ------------------------------------------------------

def examples(events):
    """{(root, node): [{"in", "out", "after", "hash", "steps", "count"}, …]}: the distinct values that
    each entry point gave to each node, in the order of the first call."""
    out = {}
    for ev in events:
        rows = out.setdefault((ev["root"], ev["node"]), [])
        row = next((r for r in rows if r["hash"] == ev["hash"]), None)
        if row is None:
            row = {"in": ev.get("in"), "out": ev.get("out"), "after": ev.get("after"), "hash": ev["hash"], "steps": [], "count": 0}
            rows.append(row)
        row["count"] += 1
        if ev.get("step") not in row["steps"]:
            row["steps"].append(ev.get("step"))
    return out


def variants(events):
    """{root: [(path, count), …]}: the distinct paths that one entry point took in one step, most
    frequent first. A path is the list of nodes in call order, with a repeat in a row shown once."""
    groups = {}
    for ev in events:
        groups.setdefault((ev.get("run"), ev.get("step"), ev["root"]), []).append(ev["node"])
    counts = {}
    for (_, _, root), nodes in groups.items():
        path = tuple(n for i, n in enumerate(nodes) if i == 0 or n != nodes[i - 1])
        counts.setdefault(root, {}).setdefault(path, 0)
        counts[root][path] += 1
    return {r: sorted(c.items(), key=lambda x: (-x[1], x[0])) for r, c in counts.items()}


def matrix(events):
    """{root: {node: number of calls}}."""
    m = {}
    for ev in events:
        row = m.setdefault(ev["root"], {})
        row[ev["node"]] = row.get(ev["node"], 0) + 1
    return m


def diff(a, b):
    """The first step where two logs of the same run differ, or None.
    Each log is cut into steps; in each step the node and the hash of each call are compared in order."""
    def by_step(evs):
        steps = {}
        for ev in evs:
            steps.setdefault(ev.get("step"), []).append(ev)
        return steps
    sa, sb = by_step(a), by_step(b)
    order = list(dict.fromkeys([e.get("step") for e in a] + [e.get("step") for e in b]))
    keys = ("node", "root", "in", "out", "hash")
    for st in order:
        ea, eb = sa.get(st, []), sb.get(st, [])
        for i in range(max(len(ea), len(eb))):
            x = ea[i] if i < len(ea) else None
            y = eb[i] if i < len(eb) else None
            if x is None or y is None or (x["node"], x["hash"]) != (y["node"], y["hash"]):
                return {"step": st, "index": i, "a": x and {k: x.get(k) for k in keys}, "b": y and {k: y.get(k) for k in keys}}
    return None


def _short(v, n=70):
    s = json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[: n - 1] + "…"


def report(events):
    """A Markdown page of the three views."""
    m, ex, va = matrix(events), examples(events), variants(events)
    nodes = sorted({e["node"] for e in events})
    roots = sorted(m)
    out = [f"# Event log: {len(events)} events, {len(roots)} roots, {len(nodes)} nodes", "",
           "## Root × node (number of calls)", "",
           "| root | " + " | ".join(f"`{n.split('.')[-1]}`" for n in nodes) + " |", "|---|" + "---|" * len(nodes)]
    out += [f"| `{r}` | " + " | ".join(str(m[r].get(n, "")) for n in nodes) + " |" for r in roots]
    out += ["", "## Variants (the distinct paths of each root in one step)", ""]
    for r in roots:
        out.append(f"- `{r}`")
        out += [f"  - {c} × " + " → ".join(n.split(".")[-1] for n in p) for p, c in va.get(r, [])]
    out += ["", "## Examples of each (root, node)", "", "| root | node | in | out | steps | calls |", "|---|---|---|---|---|---|"]
    for (r, n), rows in sorted(ex.items()):
        for row in rows:
            steps = ", ".join(map(str, row["steps"]))
            out.append(f"| `{r}` | `{n}` | `{_short(row['in'])}` | `{_short(row['out'], 40)}` | {steps} | {row['count']} |")
    return "\n".join(out) + "\n"


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Views of a Code-Wire event log")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="matrix, variants and examples as Markdown")
    r.add_argument("log")
    r.add_argument("--out")
    d = sub.add_parser("diff", help="the first step where two logs differ (exit 1 when they differ)")
    d.add_argument("a")
    d.add_argument("b")
    a = ap.parse_args(argv)
    if a.cmd == "report":
        text = report(read(a.log))
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    first = diff(read(a.a), read(a.b))
    if first is None:
        print("same: every step has the same nodes and hashes")
        return 0
    print(f"differ at step {first['step']}, call {first['index'] + 1}:")
    print("  a:", _short(first["a"], 300))
    print("  b:", _short(first["b"], 300))
    return 1


if __name__ == "__main__":
    sys.exit(main())
