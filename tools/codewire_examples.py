"""Code-Wire examples check: are the graph's `examples:` (literal thread, Metodología §3.1) still
what the code produces?

Each `ejemplos:` line names its thread, e.g. `(AC-1) ...`. For a thread with a recorded trace
(`cw_record_plugin.py`), the literal anchors of the line must appear in one recorded call of that node:
    0x...           hex values      -> compared as integers (0x1000 == 4096)
    0xK: 0xV        address/value (also `[0xK] = 0xV`) -> that key must map to that value, not just both exist
    `...`           literal text    -> substring of the call (inputs, output, modified inputs, files read/written)
    "..."  «...»    quoted strings  -> same; an elision `...`/`…` splits it and each piece must appear
Prose around the anchors is not checked. A line marked «inferred» or «synthetic» is not observed: skipped.

    python codewire_examples.py --graph G1.md [--graph G2.md] --trace AC-1=trace.json --out report.md
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codewire_extract as cw  # noqa: E402

ELISION = re.compile(r"\.\.\.|…")


PAIR = re.compile(r"(0x[0-9A-Fa-f]+)\]?\s*[:=]\s*(0x[0-9A-Fa-f]+)\b")


def as_int(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and re.fullmatch(r"0x[0-9A-Fa-f]+", v):
        return int(v, 16)
    return None


def anchors(line):
    """(ints, texts, pairs) a line commits to; the leading `(THREAD ...)` tag is not an anchor."""
    body = re.sub(r"^\([^)]*\)\s*", "", line)
    texts = []
    for m in re.finditer(r"`([^`]+)`|\"([^\"]+)\"|«([^»]+)»", body):
        t = next(g for g in m.groups() if g is not None)
        texts += [p.strip() for p in ELISION.split(t) if len(p.strip()) >= 3]
    ints = {int(h, 16) for h in re.findall(r"\b0x[0-9A-Fa-f]+\b", body)}
    pairs = {(int(k, 16), int(v, 16)) for k, v in PAIR.findall(body)}
    return ints, texts, pairs


def haystack(call):
    """All string leaves (joined), every integer a recorded call contains however it was rendered,
    and every int -> int dict entry (a memory map)."""
    strings, ints, pairs = [], set(), set()
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
        elif isinstance(v, str):
            strings.append(v.replace("\\", "/"))  # a Windows path matches the `/` the graph writes
            ints |= {int(h, 16) for h in re.findall(r"0x[0-9A-Fa-f]+", v)}
            ints |= {int(d) for d in re.findall(r"(?<![\w.])\d+(?![\w.])", v)}
    return "\n".join(strings), ints, pairs


def check_line(line, calls):
    """Missing anchors against the best recorded call (fewest misses); [] = the line holds."""
    ints, texts, pairs = anchors(line)
    best = None
    for call in calls:
        text, have, have_pairs = haystack(call)
        missing = ([hex(i) for i in sorted(ints - have)] + [t for t in texts if t not in text]
                   + [f"{hex(k)}: {hex(v)}" for k, v in sorted(pairs - have_pairs)])
        if best is None or len(missing) < len(best):
            best = missing
    return best


def check(graph_nodes, traces):
    """One row per `examples:` line: (node, thread, status, detail)."""
    rows = []
    for node in graph_nodes:
        for line in node["examples"]:
            m = re.match(r"\(([^,)]+)", line)
            thread = m.group(1).strip() if m else "?"
            if thread not in traces:
                rows.append((node["name"], thread, "no_trace", "no recorded run for this thread"))
            elif re.search(r"\binferred\b|\bsynthetic\b", line[:60]):
                rows.append((node["name"], thread, "not_observed", "marked as not observed in the run"))
            elif not traces[thread].get(node["name"]):
                rows.append((node["name"], thread, "node_not_run", "the run never called this node"))
            else:
                missing = check_line(line, traces[thread][node["name"]])
                rows.append((node["name"], thread, "ok" if not missing else "drift",
                             "" if not missing else "not in the run: " + ", ".join(f"`{x}`" for x in missing)))
    return rows


def render(rows, traces):
    count = {s: sum(1 for r in rows if r[2] == s) for s in ("ok", "drift", "node_not_run", "not_observed", "no_trace")}
    out = ["# Code-Wire examples check", "",
           f"- Threads with a recorded run: {', '.join(sorted(traces)) or 'none'}",
           f"- Example lines: {len(rows)} · ok {count['ok']} · drift {count['drift']} · node not run "
           f"{count['node_not_run']} · not observed {count['not_observed']} · no trace {count['no_trace']}", "",
           "| node | thread | status | detail |", "|---|---|---|---|"]
    out += [f"| `{n}` | {t} | {s} | {d} |" for n, t, s, d in rows]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--graph", required=True, type=Path, action="append")
    ap.add_argument("--trace", required=True, action="append", help="THREAD=trace.json (from cw_record_plugin)")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    nodes, _, _, _ = cw.load_graphs([g.read_text(encoding="utf-8") for g in a.graph])
    traces = {}
    for t in a.trace:
        name, _, path = t.partition("=")
        traces[name] = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = check(nodes, traces)
    a.out.write_text(render(rows, traces), encoding="utf-8")
    drift = sum(1 for r in rows if r[2] == "drift")
    print(f"{len(rows)} example lines, {drift} drift -> {a.out}")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
