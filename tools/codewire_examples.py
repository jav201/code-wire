"""Code-Wire examples check: are the graph's `examples:` (literal thread, Metodologia.md §2) still
what the code produces?

Each `ejemplos:` line names its thread, e.g. `(AC-1) ...`. For a thread with a recorded trace
(`cw_record_plugin.py`), the literal anchors of the line must appear in one recorded call of that node:
    0x...           hex values      -> compared as integers (0x1000 == 4096)
    0xK: 0xV        address/value (also `[0xK] = 0xV`) -> that key must map to that value, not just both exist
    `...`           literal text    -> substring of the call (inputs, output, modified inputs, files read/written)
    "..."  «...»    quoted strings  -> same; an elision `...`/`…` splits it and each piece must appear
Quoted text of 1 or 2 characters (`"ok"`) must equal a whole recorded string, not a part of one.
    `6`             a decimal number in backticks -> compared as an integer (v2.6)
    `30.0`          a float in backticks -> compared with a tolerance (A1)
Prose around the anchors is not checked. A line marked `unrecorded` in its source has no recording yet: it is counted, not checked.
A line with no anchor is `no_anchor`, not `ok`. A node that the recorder skipped (no def yet) is `no_def`.
v2.6: a bare number (not in backticks, quotes or parentheses) gets a warning, because the check does not
compare it. A1: a recorded string matches in its own form, and also with each backslash as `/`:
a Windows path matches, and so does a Markdown escape before a dot. A text anchor and a recorded
string are compared with each run of spaces as one space. The report starts with the count of the lines
that no recording backs: a line with no recorded run of its thread, or a line marked `unrecorded`.
A3a: a line whose source names its root (`(U2, U2.4, root TuiApp.on_button_pressed)`) compares only with
the recorded calls of that root; with no such call, the line is `root_not_run`.

    python codewire_examples.py --graph G1.md [--graph G2.md] --trace AC-1=trace.json --out report.md
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codewire_events as events  # noqa: E402
import codewire_extract as cw  # noqa: E402

ELISION = re.compile(r"\.\.\.|…")
DECIMAL = re.compile(r"-?\d+")
FLOAT = re.compile(r"-?\d+\.\d+")
FLOAT_IN_TEXT = re.compile(r"(?<![\w.])-?\d+\.\d+(?![\w.])")
SPACES = re.compile(r"\s+")
EXPECT_NONE = re.compile(r"→\s*expect none\b")
FAILS = ("drift", "root_not_run", "step_not_run")


def spaced(text):
    """Each run of spaces as one space: the padding of a painted screen is not part of the value."""
    return SPACES.sub(" ", text).strip()


def near(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


UNRECORDED = re.compile(r"\bunrecorded\b")
PAIR = re.compile(r"(0x[0-9A-Fa-f]+)\]?\s*[:=]\s*(0x[0-9A-Fa-f]+)\b")


def as_int(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and re.fullmatch(r"0x[0-9A-Fa-f]+", v):
        return int(v, 16)
    return None


def anchors(line):
    """(ints, texts, pairs, exact, floats) a line commits to; the leading `(THREAD ...)` tag is not an anchor.
    `exact`: quoted text of 1 or 2 characters, which only a whole recorded string can match."""
    body = re.sub(r"^\([^)]*\)\s*", "", line)
    texts, exact, floats = [], [], []
    ints = {int(h, 16) for h in re.findall(r"\b0x[0-9A-Fa-f]+\b", body)}
    for m in re.finditer(r"`([^`]+)`|\"([^\"]+)\"|«([^»]+)»", body):
        t = next(g for g in m.groups() if g is not None)
        if m.group(1) is not None and DECIMAL.fullmatch(t.strip()):  # `6`: a number anchor (v2.6)
            ints.add(int(t))
            continue
        if m.group(1) is not None and FLOAT.fullmatch(t.strip()):  # `30.0`: a float anchor (A1)
            floats.append(float(t))
            continue
        pieces = [spaced(p) for p in ELISION.split(t)]
        if len(pieces) == 1 and 0 < len(pieces[0]) < 3:
            exact.append(pieces[0])
        texts += [p for p in pieces if len(p) >= 3]
    pairs = {(int(k, 16), int(v, 16)) for k, v in PAIR.findall(body)}
    return ints, texts, pairs, exact, floats


def bare_numbers(line):
    """Decimal numbers that the check does not compare: not in backticks, quotes, «» or parentheses
    (a count such as `(2 of 3)` is not an anchor), and not a hex value or a part of a name."""
    body = re.sub(r"^\([^)]*\)\s*", "", line)
    body = re.sub(r"`[^`]*`|\"[^\"]*\"|«[^»]*»", " ", body)
    while re.search(r"\([^()]*\)", body):
        body = re.sub(r"\([^()]*\)", " ", body)
    body = re.sub(r"\b0x[0-9A-Fa-f]+\b", " ", body)
    return re.findall(r"(?<![\w.\-/:\[])\d+(?:\.\d+)?(?![\w.\-/:\]])", body)


def haystack(call):
    """All string leaves (joined), every integer a recorded call contains however it was rendered,
    every int -> int dict entry (a memory map), and every float."""
    strings, ints, pairs, floats = [], set(), set(), []
    stack = [call]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            for k, x in v.items():
                stack += [k, x]
                if as_int(k) is not None and as_int(x) is not None:
                    pairs.add((as_int(k), as_int(x)))
        elif isinstance(v, list):
            stack += v
        elif isinstance(v, bool) or v is None:
            continue
        elif isinstance(v, int):
            ints.add(v)
            floats.append(float(v))
        elif isinstance(v, float):
            floats.append(v)
            if v.is_integer():
                ints.add(int(v))
        elif isinstance(v, str):
            # the string as recorded, and with `/` for `\`: a Windows path matches the `/` of the graph,
            # and an escaped `patch\.json` still matches its own form
            strings += list(dict.fromkeys(spaced(x) for x in (v, v.replace("\\", "/"))))
            floats += [float(f) for f in FLOAT_IN_TEXT.findall(v)]
            ints |= {int(h, 16) for h in re.findall(r"0x[0-9A-Fa-f]+", v)}
            ints |= {int(d) for d in re.findall(r"(?<![\w.])\d+(?![\w.])", v)}
    return "\n".join(strings), ints, pairs, floats


def check_line(line, calls):
    """Missing anchors against the best recorded call (fewest misses); [] = the line holds."""
    ints, texts, pairs, exact, floats = anchors(line)
    best = None
    for call in calls:
        text, have, have_pairs, have_floats = haystack(call)
        leaves = set(text.split("\n"))
        missing = ([hex(i) for i in sorted(ints - have)] + [t for t in texts if t not in text]
                   + [t for t in exact if t not in leaves]
                   + [f"{hex(k)}: {hex(v)}" for k, v in sorted(pairs - have_pairs)]
                   + [str(f) for f in floats if not any(near(f, h) for h in have_floats)])
        if best is None or len(missing) < len(best):
            best = missing
    return best


def check(graph_nodes, traces):
    """One row per `examples:` line: (node, thread, status, detail, bare numbers)."""
    rows = []
    for node in graph_nodes:
        for line in node["examples"]:
            src = cw.example_source(line)
            thread = src["thread"] or "?"
            bare = bare_numbers(line)
            if src["marker"] == "unrecorded" and src["thread"] is None:
                rows.append((node["name"], "-", "unrecorded", "marked: no recording backs it yet", bare))
            elif thread not in traces:
                rows.append((node["name"], thread, "no_trace", "no recorded run for this thread", bare))
            elif src["marker"] == "unrecorded" or UNRECORDED.search(line[:60]):
                rows.append((node["name"], thread, "unrecorded", "marked: no recording backs it yet", bare))
            elif EXPECT_NONE.search(line):
                rows.append((node["name"], thread, *expect_none(traces[thread], node["name"], src), bare))
            elif node["name"] in traces[thread].get("_skipped", []):
                rows.append((node["name"], thread, "no_def", "the node has no code yet: the recorder skipped it", bare))
            elif not traces[thread].get(node["name"]):
                rows.append((node["name"], thread, "node_not_run", "the run never called this node", bare))
            elif src["root"] and not [c for c in traces[thread][node["name"]] if c.get("root") == src["root"]]:
                rows.append((node["name"], thread, "root_not_run", f"no recorded call of this node from the root `{src['root']}`", bare))
            elif not any(anchors(line)):
                rows.append((node["name"], thread, "no_anchor", "the line has no literal value to compare", bare))
            else:
                calls = traces[thread][node["name"]]
                if src["root"]:   # A3a: a line that names its root compares only with the calls of that root
                    calls = [c for c in calls if c.get("root") == src["root"]]
                missing = check_line(line, calls)
                rows.append((node["name"], thread, "ok" if not missing else "drift",
                             "" if not missing else "not in the run: " + ", ".join(f"`{x}`" for x in missing), bare))
    return rows


def step_calls(trace, node, src):
    """The calls of `node` in the step (and from the root) that a source names."""
    return [c for c in trace.get(node, []) if c.get("step") == src["step"] and (not src["root"] or c.get("root") == src["root"])]


def step_known(trace, src):
    """None when the step can be checked, else (status, detail)."""
    if not src["step"]:
        return "not_checkable", "the source names no step"
    if "_steps" not in trace:
        return "not_checkable", "this needs an event log: a trace has no steps"
    if src["step"] not in trace["_steps"]:
        return "step_not_run", f"the log has no step `{src['step']}`"
    return None


def expect_none(trace, node, src):
    """A3b: `→ expect none`: the node has no call in that step."""
    bad = step_known(trace, src)
    if bad:
        return bad
    ran = step_calls(trace, node, src)
    return ("ok", "") if not ran else ("drift", f"the node ran {len(ran)} time(s) in step `{src['step']}`")


def check_offers(entities, traces):
    """A3b: one row per `offers:` line: (entity, control, node, thread, status, detail).
    An offer with a source holds when its node ran in that step: the control did what it promises."""
    rows = []
    for ent in entities:
        for o in ent.get("offers", []):
            src = o["source"] or {"thread": None, "step": None, "root": None}
            t = src["thread"]
            if not t:
                rows.append((ent["name"], o["control"], o["node"], "-", "not_checked", "the offer names no recorded step"))
            elif t not in traces:
                rows.append((ent["name"], o["control"], o["node"], t, "no_trace", "no recorded run for this thread"))
            elif step_known(traces[t], src):
                rows.append((ent["name"], o["control"], o["node"], t, *step_known(traces[t], src)))
            elif step_calls(traces[t], o["node"], src):
                rows.append((ent["name"], o["control"], o["node"], t, "ok", ""))
            else:
                rows.append((ent["name"], o["control"], o["node"], t, "drift",
                             f"`{o['node']}` did not run in step `{src['step']}`: the control does not do what it offers"))
    return rows


def render(rows, traces, offers=()):
    count = {s: sum(1 for r in rows if r[2] == s)
             for s in ("ok", "drift", "root_not_run", "step_not_run", "not_checkable", "no_anchor", "node_not_run", "no_def", "unrecorded", "no_trace")}
    warned = [r for r in rows if r[4]]
    no_rec = count["no_trace"] + count["unrecorded"]
    out = ["# Code-Wire examples check", "",
           f"- **Lines that no recording backs: {no_rec} of {len(rows)}** "
           f"(no recorded run of the thread {count['no_trace']}, marked `unrecorded` {count['unrecorded']})",
           f"- Threads with a recorded run: {', '.join(sorted(traces)) or 'none'}",
           f"- Checked lines: ok {count['ok']} · drift {count['drift']} · root not run {count['root_not_run']} · step not run {count['step_not_run']} · not checkable {count['not_checkable']} · no anchor {count['no_anchor']}"
           f" · node not run {count['node_not_run']} · no def {count['no_def']}",
           f"- Lines with a bare number (a warning: the check does not compare it): {len(warned)}", "",
           "| node | thread | status | detail | bare numbers |", "|---|---|---|---|---|"]
    out += [f"| `{n}` | {t} | {s} | {d} | {', '.join(b)} |" for n, t, s, d, b in rows]
    if offers:
        out += ["", "## Offers", "", "| entity | control | node | thread | status | detail |", "|---|---|---|---|---|---|"]
        out += [f"| `{e}` | \"{c}\" | `{n}` | {t} | {s} | {d} |" for e, c, n, t, s, d in offers]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--graph", required=True, type=Path, action="append")
    ap.add_argument("--trace", required=True, action="append", help="THREAD=trace.json, or THREAD=events.jsonl (an event log)")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    texts = [g.read_text(encoding="utf-8") for g in a.graph]
    nodes, _, _, _ = cw.load_graphs(texts)
    entities = [e for t in texts for e in cw.parse_entity_blocks(t)]
    traces = {}
    for t in a.trace:
        name, _, path = t.partition("=")
        if path.endswith(".jsonl"):   # an event log (A2d): every recorded call, not only three
            traces[name] = events.trace_view(events.read(path, markers=True), max_calls=None,
                                             skipped=events.read_meta(path).get("skipped", []))
        else:
            traces[name] = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = check(nodes, traces)
    offers = check_offers(entities, traces)
    a.out.write_text(render(rows, traces, offers), encoding="utf-8")
    drift = sum(1 for r in rows if r[2] in FAILS)   # a line on a root or a step that never ran does not hold
    broken = sum(1 for r in offers if r[4] in FAILS)
    no_rec = sum(1 for r in rows if r[2] in ("no_trace", "unrecorded"))
    print(f"{len(rows)} example lines, {no_rec} with no recording, {drift} drift; {len(offers)} offers, {broken} not kept -> {a.out}")
    return 1 if drift or broken else 0


if __name__ == "__main__":
    sys.exit(main())
