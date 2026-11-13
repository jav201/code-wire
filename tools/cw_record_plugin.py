"""Code-Wire recorder: a read-only pytest plugin that records the literal I/O of every graph node
while real tests run, so `codewire_examples.py` can check the graph's `ejemplos:` against it.

Generic: the nodes come from the graph files (name + `module:`), not from a hand-written list, read as
successive increments (`--layered` of the extractor). A node is recorded under its name (`module:name`
when two modules have a node of that name).
    CW_GRAPHS  graph .md files, separated by os.pathsep
    CW_OUT     trace JSON to write (no file when it is not set)
    CW_MAX     calls kept per node (default 3)
The wrapped function returns exactly what the original returns; nothing in the repo is edited.
    CW_MAX_EVENTS  events kept per (root, node) pair in the event log (default 50)
    CW_ADAPTERS    framework adapters to install, separated by commas (`textual`: cw_textual.py)
A node with no module or no def yet (a NEW node in forward) is skipped and listed in the trace key `_skipped`.
Each call is also an event of the log (`codewire_events.py`): its root, its parent and a hash.
The limit CW_MAX applies to each (root, node) pair, so each entry point keeps its own examples.
After the call, `after` holds each input that `modify:` names, and (A2g) each `[Data: Class.attribute]`
entity of `modify:` when the node is a method of that class: the value of `self.attribute` when the call
returns. A write that a worker or a later callback makes is not in it.
"""
import dataclasses
import functools
import importlib
import inspect
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codewire_events as events  # noqa: E402
import codewire_extract as cw  # noqa: E402

OUT = os.environ.get("CW_OUT")   # the trace file only when asked: no file in the repository by default
MAX_CALLS = int(os.environ.get("CW_MAX", "3"))
MAX_EVENTS = int(os.environ.get("CW_MAX_EVENTS", "50"))
TRACE = {}  # node name -> list of calls
KEPT = {}   # (root, node) -> events in the log
DEPTH = [0]


def lit(v, depth=0):
    """JSON-safe literal view of a value, bounded so a trace stays readable."""
    if isinstance(v, (str, int, float, bool, type(None))):
        return v if not isinstance(v, str) or len(v) <= 4000 else v[:4000] + "…"
    if isinstance(v, (bytes, bytearray)):
        try:
            return {"bytes": len(v), "text": bytes(v[:4000]).decode("utf-8")}
        except UnicodeDecodeError:
            return {"bytes": len(v), "ints": list(v[:64])}
    if isinstance(v, Path):
        return str(v)
    if depth >= 4:
        if isinstance(v, (set, frozenset)):   # the repr of a set has the order of the process
            return ("{" + ", ".join(sorted(map(repr, v))) + "}")[:300]
        return repr(v)[:300]
    if isinstance(v, dict):
        items = list(v.items())
        d = {str(k if not isinstance(k, int) else hex(k)): lit(x, depth + 1) for k, x in items[:40]}
        if len(items) > 40:
            d["…total"] = len(items)
        return d
    if isinstance(v, (list, tuple, set, frozenset)):
        # a set of strings has a new order in each process (hash randomization): sort it, or the
        # same run gives another hash (Textual widget classes, A2d smoke run)
        seq = sorted(v, key=repr) if isinstance(v, (set, frozenset)) else list(v)
        return [lit(x, depth + 1) for x in seq[:40]] + ([f"… total {len(seq)}"] if len(seq) > 40 else [])
    if dataclasses.is_dataclass(v):
        return {type(v).__name__: {f.name: lit(getattr(v, f.name), depth + 1) for f in dataclasses.fields(v)}}
    if hasattr(v, "__dict__") and not inspect.isroutine(v) and not inspect.ismodule(v):
        return {type(v).__name__: {k: lit(x, depth + 1) for k, x in list(vars(v).items())[:40]}}
    return repr(v)[:300]


def file_head(v, lines=400):
    """A node that takes or returns a path reads or writes that file: keep its first lines
    (enough for a thread line deep in a small input file, e.g. line 40 of an A2L)."""
    if not isinstance(v, (str, Path)) or (isinstance(v, str) and len(v) > 400):
        return None
    try:
        p = Path(v)
        if p.is_file() and p.stat().st_size <= 256 * 1024:
            return p.read_text(encoding="utf-8", errors="replace").splitlines()[:lines]
    except (OSError, ValueError):
        return None
    return None


def files_in(value):
    found = {}
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, (list, tuple)):
            stack.extend(v)
        else:
            head = file_head(v)
            if head is not None:
                found[str(v)] = head
    return found


def volatile_paths(node):
    """`volatile:` of a node as (part, path) for `events.event_hash`: an input name, `out`, the name of
    the output or of an item of a tuple output, and then the fields after the dots."""
    ins = {d["name"] for d in node.get("in", [])}
    outs = node.get("out", {}).get("names", [])
    paths = []
    for item in node.get("volatile", []):
        name, *fields = item.split(".")
        if name in ins:
            paths.append(("in", [name] + fields))
        elif name == "out" or outs == [name]:
            paths.append(("out", fields))
        elif name in outs:
            paths.append(("out", [outs.index(name)] + fields))
    return paths


def self_entities(node):
    """A2g: the `[Data: Class.attribute]` targets of `modify:` when the node is a method of `Class`:
    [(entity, [attribute, …])]. An entity of another class, or a node that is a function, gives none."""
    owner = node["name"].rsplit(".", 1)[0] if "." in node["name"] else None
    out = []
    for target in node.get("modify", []):
        m = re.match(r"^\[Data:\s*([A-Za-z_][\w.]*)\]$", target.strip())
        if not m or owner is None:
            continue
        cls, _, attrs = m.group(1).partition(".")
        if cls == owner.split(".")[-1] and attrs:
            out.append((target.strip(), attrs.split(".")))
    return out


def wrap(node, fn):
    sig = inspect.signature(fn)
    volatile = volatile_paths(node)
    entities = self_entities(node)
    # Q28: a `modify:` on an input (`mem_map`, `document.entries[].status`) is recorded after the call
    modified = [m.split(".")[0].split("[")[0] for m in node["modify"] if m and not m.startswith("[")]

    name = node.get("key", node["name"])

    @functools.wraps(fn)
    def w(*a, **k):
        ev = events.begin(name, sys._getframe(1), getattr(fn, "__code__", None), a + tuple(k.values()))
        key = (ev["root"], name)
        if KEPT.get(key, 0) >= MAX_EVENTS:
            try:
                return fn(*a, **k)
            finally:
                events.end(ev)
        KEPT[key] = KEPT.get(key, 0) + 1
        try:
            bound = sig.bind(*a, **k)
            args = dict(bound.arguments)
        except TypeError:
            bound, args = None, {"args": a, "kwargs": k}
        call = {"test": os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0], "depth": DEPTH[0],
                "root": ev["root"], "parent": ev["parent"],
                "in": {n: lit(v) for n, v in args.items() if n != "self"}}
        calls = TRACE.setdefault(name, [])
        if sum(1 for c in calls if c.get("root") == ev["root"]) < MAX_CALLS:
            calls.append(call)
        DEPTH[0] += 1
        try:
            r = fn(*a, **k)
        except BaseException:
            DEPTH[0] -= 1
            call["raised"] = True
            events.end(ev, call, volatile)
            raise
        DEPTH[0] -= 1
        is_init = node["name"].endswith(".__init__")
        call["out"] = lit(a[0] if is_init else r)
        if bound is not None:
            after = {n: lit(bound.arguments[n]) for n in modified if n in bound.arguments}
            obj = bound.arguments.get("self")
            for entity, attrs in entities if obj is not None else ():
                value = obj
                try:
                    for a in attrs:
                        value = getattr(value, a)
                except AttributeError:
                    continue   # the object has no such attribute: nothing to keep
                after[entity] = lit(value)
            if after:
                call["after"] = after
        files = files_in(list(args.values()) + [r])
        if files:
            call["files"] = files
        events.end(ev, call, volatile)
        return r
    return w


def resolve(node):
    """(owner, attr, function) for a node: `module:` gives the module, the name gives the attribute; a real
    attribute first, then the name after a module prefix."""
    mod = importlib.import_module(node["module"][:-3].replace("/", "."))

    def walk(name):
        owner, parts = mod, name.split(".")
        for p in parts[:-1]:
            owner = getattr(owner, p)
        return owner, parts[-1], getattr(owner, parts[-1])
    try:
        return walk(node["name"])
    except AttributeError:
        short = cw.drop_module_prefix(node["name"], node["module"])
        if short is None:
            raise
        return walk(short)


def pytest_configure(config):
    install([p for p in os.environ.get("CW_GRAPHS", "").split(os.pathsep) if p],
            [n.strip() for n in os.environ.get("CW_ADAPTERS", "").split(",") if n.strip()])


def install(graph_paths, adapters=()):
    """Wrap every node of the graphs that has code; install the adapters (e.g. `textual`).
    pytest calls it through `pytest_configure`; `cw_record_run.py` calls it for a script."""
    for name in adapters:
        importlib.import_module(f"cw_{name}").install()
    texts = [Path(p).read_text(encoding="utf-8") for p in graph_paths]
    nodes, _, _, _ = cw.load_graphs(texts, layered=True)
    originals, skipped = {}, []
    for node in nodes:
        try:
            owner, attr, fn = resolve(node)
        except (TypeError, ImportError, AttributeError):  # no `module:`, no module file, or no def yet
            skipped.append(node["key"])
            continue
        w = wrap(node, fn)
        setattr(owner, attr, w)
        originals[id(fn)] = (fn, w)
    TRACE["_skipped"] = skipped
    # `from x import f` copies taken before the patch still point at the original: rebind them
    for m in list(sys.modules.values()):
        for attr, v in list(getattr(m, "__dict__", {}).items()):
            if id(v) in originals and originals[id(v)][0] is v:
                setattr(m, attr, originals[id(v)][1])


def pytest_unconfigure(config):
    save()


def save(events_path=None, trace_path=None):
    """Write the event log and the trace."""
    events.write(events_path, skipped=TRACE.get("_skipped", []))
    if trace_path or OUT:
        with open(trace_path or OUT, "w", encoding="utf-8") as f:
            json.dump(TRACE, f, indent=1, ensure_ascii=False, default=str)
