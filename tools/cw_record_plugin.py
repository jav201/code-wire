"""Code-Wire recorder: a read-only pytest plugin that records the literal I/O of every graph node
while real tests run, so `codewire_examples.py` can check the graph's `ejemplos:` against it.

Generic: the nodes come from the graph files (name + `module:`), not from a hand-written list.
    CW_GRAPHS  graph .md files, separated by os.pathsep
    CW_OUT     trace JSON to write (default cw-trace.json)
    CW_MAX     calls kept per node (default 3)
The wrapped function returns exactly what the original returns; nothing in the repo is edited.
A node with no module or no def yet (a NEW node in forward) is skipped and listed in the trace key `_skipped`.
"""
import dataclasses
import functools
import importlib
import inspect
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codewire_extract as cw  # noqa: E402

OUT = os.environ.get("CW_OUT", "cw-trace.json")
MAX_CALLS = int(os.environ.get("CW_MAX", "3"))
TRACE = {}  # node name -> list of calls
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
        return repr(v)[:300]
    if isinstance(v, dict):
        items = list(v.items())
        d = {str(k if not isinstance(k, int) else hex(k)): lit(x, depth + 1) for k, x in items[:40]}
        if len(items) > 40:
            d["…total"] = len(items)
        return d
    if isinstance(v, (list, tuple, set, frozenset)):
        seq = list(v)
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


def wrap(node, fn):
    sig = inspect.signature(fn)
    # Q28: a `modify:` on an input (`mem_map`, `document.entries[].status`) is recorded after the call
    modified = [m.split(".")[0].split("[")[0] for m in node["modify"] if m and not m.startswith("[")]

    @functools.wraps(fn)
    def w(*a, **k):
        calls = TRACE.setdefault(node["name"], [])
        if len(calls) >= MAX_CALLS:
            return fn(*a, **k)
        try:
            bound = sig.bind(*a, **k)
            args = dict(bound.arguments)
        except TypeError:
            bound, args = None, {"args": a, "kwargs": k}
        call = {"test": os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0], "depth": DEPTH[0],
                "in": {n: lit(v) for n, v in args.items() if n != "self"}}
        calls.append(call)
        DEPTH[0] += 1
        try:
            r = fn(*a, **k)
        finally:
            DEPTH[0] -= 1
        is_init = node["name"].endswith(".__init__")
        call["out"] = lit(a[0] if is_init else r)
        if bound is not None:
            after = {n: lit(bound.arguments[n]) for n in modified if n in bound.arguments}
            if after:
                call["after"] = after
        files = files_in(list(args.values()) + [r])
        if files:
            call["files"] = files
        return r
    return w


def resolve(node):
    """(owner, attr, function) for a node: `module:` gives the module, the name gives the attribute."""
    mod = importlib.import_module(node["module"][:-3].replace("/", "."))
    parts = node["name"].split(".")
    owner = mod
    for p in parts[:-1]:
        owner = getattr(owner, p)
    return owner, parts[-1], getattr(owner, parts[-1])


def pytest_configure(config):
    texts = [Path(p).read_text(encoding="utf-8") for p in os.environ.get("CW_GRAPHS", "").split(os.pathsep) if p]
    nodes, _, _, _ = cw.load_graphs(texts)
    originals, skipped = {}, []
    for node in nodes:
        try:
            owner, attr, fn = resolve(node)
        except (TypeError, ImportError, AttributeError):  # no `module:`, no module file, or no def yet
            skipped.append(node["name"])
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
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(TRACE, f, indent=1, ensure_ascii=False, default=str)
