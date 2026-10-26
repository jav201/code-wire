"""Code-Wire coherence check: C2, C3, C4, C7 and C10 on one or more graph files (v2.6).

Usage: python codewire_coherence.py --graph G1.md [--graph G2.md] [--trace T=trace.json] --out report.md

    C2   each input has an edge to its port: from a node port, a caller edge (a node with no port),
         an entity or an `[Outside: …]` item of `## Boundary`
    C3   each output is used: an edge from its port, a `when:` that names it, or a `discarded:` line
    C4   each node is reachable from a source and reaches a sink (entities and outside items)
    C7   the names of nodes and entities are unique
    C10  each `[…]` target of `modify:` is declared, and each entity is read or written

The report also lists the fields of each entity that an edge names with a field (`[Data: X].f`, A3d):
which nodes read each field and which write it. It is info. Two readers of two fields of one entity are
two sources of truth (data MF-8, CW-D-7).

An input with a default value and no edge is info, not open: the default gives the value.
An input of a node that only a node-to-node edge with no ports calls is listed apart. It is open,
because `Metodologia.md` §3.3 asks for a port on a caller edge.
With `--trace` (recordings of `cw_record_plugin.py`), each open item gets the status of its node
(NEW / CHANGED / SHIPPED). The PDR gate (Metodologia §8) asks C2 only on NEW and CHANGED nodes.
Exit code 1 when an item of C2, C3, C4, C7 or C10 is open. Stdlib only.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codewire_examples as ce  # noqa: E402
import codewire_extract as cw  # noqa: E402


def port_root(port):
    """The output or input name at the start of a port: `entries[].status` -> `entries`, `ok is False` -> `ok`."""
    return re.split(r"[.\[\s]", port or "")[0]


def endpoint(text, names):
    """(node, output) when `text` starts with `<node>.<output>` of a known node, the longest name first.
    A node name can have spaces (`Read file.ok is False`), so the text is not split at the first space."""
    for name in sorted(names, key=len, reverse=True):
        if text.startswith(name + "."):
            return name, port_root(text[len(name) + 1:])
    return None


def check(texts):
    """{rule: [items]} for one set of graph files."""
    nodes, edges, entities, conflicts = cw.load_graphs(texts)
    discarded = [d for md in texts for d in cw.parse_discarded(md)]
    names = {n["name"] for n in nodes}
    res = {"C7": [k for k, v in collections.Counter([n["name"] for n in nodes] + entities).items() if v > 1]
           + [f"{c} (two contracts)" for c in conflicts]}

    fed = {(e["dst"]["node"], port_root(e["dst"]["port"])) for e in edges if e["dst"]["node"] and e["dst"]["port"]}
    called = {e["dst"]["node"] for e in edges
              if e["src"]["node"] and not e["src"]["port"] and e["dst"]["node"] and not e["dst"]["port"]}
    res["C2"], res["C2_default"], res["C2_call"] = [], [], []
    for n in nodes:
        for p in n["in"]:
            if p["kind"] == "self" or (n["name"], p["name"]) in fed:
                continue
            key = "C2_default" if p["default"] is not None else "C2_call" if n["name"] in called else "C2"
            res[key].append((n["name"], p["name"]))

    used = {(e["src"]["node"], port_root(e["src"]["port"])) for e in edges if e["src"]["node"] and e["src"]["port"]}
    # `when: <node>.<output> ...` and `discarded: <node>.<output>` use that output (v2.6)
    named = [e["when"] for e in edges if e["when"]] + [d["port"] for d in discarded]
    for text in named:
        ep = endpoint(text, names)
        if ep:
            used.add(ep)
    res["C3"] = [(n["name"], o) for n in nodes for o in n["out"]["names"] if (n["name"], o) not in used]

    adj = collections.defaultdict(set)
    for e in edges:
        a = e["src"]["node"] or e["src"]["entity"]
        b = e["dst"]["node"] or e["dst"]["entity"]
        if a and b:
            adj[a].add(b)
        gate = endpoint(e["when"], names) if e["when"] else None
        if gate and b:  # `when: <node>.<output>`: that node feeds the edge it selects
            adj[gate[0]].add(b)
    for n in nodes:
        adj[n["name"]] |= set(n["inner"]) | {t for t in n["modify"] if t.startswith("[")}
    radj = collections.defaultdict(set)
    for a, bs in adj.items():
        for b in bs:
            radj[b].add(a)

    def reach(start, g):
        seen, stack = set(start), list(start)
        while stack:
            for y in g[stack.pop()]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        return seen

    ends = set(entities)
    res["C4_from"] = sorted(n for n in names if n not in reach(ends, adj))
    res["C4_to"] = sorted(n for n in names if n not in reach(ends, radj))

    mods = {t for n in nodes for t in n["modify"] if t.startswith("[")}
    touched = {e[s]["entity"] for e in edges for s in ("src", "dst") if e[s]["entity"]} | mods
    res["C10_target"] = sorted(mods - set(entities))
    res["C10_orphan"] = [e for e in entities if e not in touched]
    return nodes, res


def fields(nodes, edges):
    """{entity: {field: {"read": set, "write": set}}} for each entity that an edge names with a field.
    A write of the whole entity (an edge with no field, or `modify:`) is under the field `*`."""
    named = {e[s]["entity"] for e in edges for s in ("src", "dst") if e[s]["entity"] and e[s].get("field")}
    out = {x: collections.defaultdict(lambda: {"read": set(), "write": set()}) for x in named}
    for e in edges:
        src, dst = e["src"], e["dst"]
        if src["entity"] in named and dst["node"]:
            out[src["entity"]][src["field"] or "*"]["read"].add(dst["node"])
        if dst["entity"] in named and src["node"]:
            out[dst["entity"]][dst["field"] or "*"]["write"].add(src["node"])
    for n in nodes:
        for t in n["modify"]:
            if t in named:
                out[t]["*"]["write"].add(n["name"])
    return out


def render_fields(view):
    if not view:
        return []
    out = ["", "## Fields of an entity (info, A3d)", "",
           "A row for each field that an edge names. A writer of the whole entity is under `*`.", "",
           "| entity | field | read by | written by |", "|---|---|---|---|"]
    names = lambda xs: ", ".join(f"`{x}`" for x in sorted(xs)) or "—"  # noqa: E731
    for ent in sorted(view):
        whole = view[ent]["*"]["write"] if "*" in view[ent] else set()
        for f in sorted(view[ent], key=lambda f: (f == "*", f)):
            row = view[ent][f]
            note = "" if f == "*" or row["write"] or whole or not row["read"] else " (no node of the graph writes it)"
            out.append(f"| `{ent}` | `{f}` | {names(row['read'])} | {names(row['write'])}{note} |")
    return out


TITLES = [("C2", "C2 · input with no edge"), ("C2_default", "C2 · info: input with a default value and no edge"),
          ("C2_call", "C2 · input that only a node-to-node call edge (no ports) reaches: open under §3.3"),
          ("C3", "C3 · output that nothing uses"), ("C4_from", "C4 · node that no source reaches"),
          ("C4_to", "C4 · node that reaches no sink"), ("C7", "C7 · name used two times"),
          ("C10_target", "C10 · `modify:` target that is not declared"), ("C10_orphan", "C10 · entity that no node reads or writes")]


def render(res, status, view=None):
    def item(x):
        node = x[0] if isinstance(x, tuple) else x
        text = ".".join(x) if isinstance(x, tuple) else x
        tag = f" · {status[node][0]}" if node in status else ""
        return f"- `{text}`{tag}"

    out = ["# Code-Wire coherence check", "", "| Rule | Open |", "|---|---|"]
    out += [f"| {t} | {len(res[k])} |" for k, t in TITLES]
    if status:
        gate = [x for x in res["C2"] + res["C2_call"] if status.get(x[0], ("?",))[0] in ("NEW", "CHANGED")]
        out += ["", f"PDR gate, C2 on the NEW and CHANGED nodes: {len(gate)} open."]
    for k, t in TITLES:
        if res[k]:
            out += ["", f"## {t}", ""] + [item(x) for x in res[k]]
    out += render_fields(view)
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--graph", required=True, type=Path, action="append")
    ap.add_argument("--trace", action="append", default=[], help="THREAD=trace.json, for the node status")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    texts = [g.read_text(encoding="utf-8") for g in a.graph]
    nodes, res = check(texts)
    view = fields(nodes, cw.load_graphs(texts)[1])
    traces = {}
    for t in a.trace:
        name, _, path = t.partition("=")
        traces[name] = json.loads(Path(path).read_text(encoding="utf-8"))
    a.out.write_text(render(res, ce.node_status(nodes, traces), view), encoding="utf-8")
    opened = sum(len(v) for k, v in res.items() if k != "C2_default")
    print(" ".join(f"{k}={len(v)}" for k, v in res.items()) + f" -> {a.out}")
    return 1 if opened else 0


if __name__ == "__main__":
    sys.exit(main())
