"""Code-Wire inventory: which functions of a Python repo are node candidates (Metodologia.md §3.4), and
which flow each one belongs to. The draft the graph text starts from (reverse direction, D2).

Every def under the package is classified by fixed rules, no judgement:
    ui         defined in a module that imports textual, in a presentation module, or a method of a
               class whose bases are UI classes. Goes to the high-level UI map, not the domain map.
    handler    a method of the App class named like an event/action handler (on_*, action_*, ...): UI.
    app        any other method of the App class, or a module-level function of its module:
               orchestration that may hold domain steps; its flow is decided by hand.
    trivial    dunder (except __init__/__call__), @property, nested function: lives inside its node.
    private    `_name` outside UI: a helper unless the hand pass promotes it.
    candidate  everything else: a public function or method of a domain module.
The flow comes from the module (FLOWS); the App methods have none until the hand pass gives one.
`tests` = test files that contain the function's name as a word (for `__init__`, the class name).
Static: a match does not prove a test calls it, and 0 does not prove none reaches it; not coverage.

    python codewire_inventory.py --repo <worktree> --out <dir>    -> inventory.json, inventory.md
"""
import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codewire_extract as cw  # noqa: E402

PACKAGE = "app"
APP_CLASS = "TuiApp"
# module prefix (relative path) -> flow; the first match wins, so the specific ones go first
FLOWS = [
    ("app/tui/services/validation_service.py", "F2"), ("app/validation/", "F2"),
    ("app/tui/changes/", "F3"), ("app/tui/services/change_service.py", "F3"),
    ("app/tui/services/flow_", "F4"), ("app/tui/services/variant_execution_service.py", "F4"),
    ("app/tui/operations/", "F5"), ("app/tui/services/operation_service.py", "F5"),
    ("app/compare.py", "F6"), ("app/tui/services/compare_service.py", "F6"),
    ("app/tui/services/diff_report_service.py", "F6"), ("app/tui/services/before_after_service.py", "F6"),
    ("app/tui/services/report_", "F7"), ("app/tui/services/markdown_safety.py", "F7"),
    ("app/tui/services/manifest_writer.py", "F7"),
    ("app/tui/workspace.py", "F8"), ("app/tui/services/project_gather_service.py", "F8"),
    ("app/tui/services/folder_open_service.py", "F8"),
    ("app/tui/services/entropy_service.py", "F9"), ("app/segment_ops.py", "F9"), ("app/range_index.py", "F9"),
    ("app/cli.py", "F10"),
    ("app/core.py", "F1"), ("app/hexfile.py", "F1"), ("app/utils.py", "F1"), ("app/tui/a2l", "F1"),
    ("app/tui/mac.py", "F1"), ("app/tui/models.py", "F1"), ("app/tui/services/load_service.py", "F1"),
    ("app/tui/services/a2l_service.py", "F1"),
]
FLOW_NAMES = {"F1": "Load", "F2": "Cross-validation", "F3": "Patch", "F4": "Flows", "F5": "CRC operations",
              "F6": "Comparison", "F7": "Reports", "F8": "Project", "F9": "Analysis", "F10": "CLI"}
# no textual import, but they only decide how things look
PRESENTATION = ("app/render/", "app/tui/legend.py", "app/tui/color_policy.py",
                "app/tui/entropy_style.py", "app/tui/insight_style.py")
UI_BASES = re.compile(r"^(App|Screen|ModalScreen|Widget|Static|Container|ScrollableContainer|Horizontal|Vertical|"
                      r"Button|Input|TextArea|Message|CappedTextArea|WindowSection)\b")
HANDLER = re.compile(r"^_?(on_|action_|watch_|key_|compose$|check_action$)")
KINDS = ("candidate", "private", "app", "trivial", "handler", "ui")


def flow_of(rel):
    return next((f for prefix, f in FLOWS if rel.startswith(prefix)), None)


def is_ui_module(tree, rel):
    if rel.startswith(PRESENTATION):
        return True
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "textual":
            return True
        if isinstance(n, ast.Import) and any(a.name.split(".")[0] == "textual" for a in n.names):
            return True
    return False


def classes_with_bases(tree):
    return {c.name: [ast.unparse(b) for b in c.bases] for c in ast.walk(tree) if isinstance(c, ast.ClassDef)}


def classify(qual, fn, cls, bases, ui_module, app_module=False):
    name = fn.name
    if cls == APP_CLASS:
        return "handler" if HANDLER.match(name) else "app"
    if app_module and cls is None and ".<locals>." not in qual:
        return "app"  # module-level functions next to the App: row states, payload helpers
    if ui_module or (cls and any(UI_BASES.match(b) for b in bases.get(cls, []))):
        return "ui"
    if ".<locals>." in qual or any(ast.unparse(d) in ("property", "cached_property") or ast.unparse(d).endswith(".setter")
                                   for d in fn.decorator_list):
        return "trivial"
    if name.startswith("__") and name.endswith("__") and name not in ("__init__", "__call__"):
        return "trivial"
    if name.startswith("_") and name not in ("__init__", "__call__"):
        return "private"
    return "candidate"


def test_words(repo):
    """{word: number of test files containing it}."""
    count = Counter()
    for p in (repo / "tests").rglob("*.py"):
        count.update(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", p.read_text(encoding="utf-8", errors="replace"))))
    return count


def inventory(repo):
    parsed, failed = cw.parse_files(repo)
    words = test_words(repo) if (repo / "tests").is_dir() else Counter()
    rows = []
    for rel, (lines, tree) in sorted(parsed.items()):
        if not rel.startswith(PACKAGE + "/"):
            continue
        ui_module, bases = is_ui_module(tree, rel), classes_with_bases(tree)
        app_module = APP_CLASS in bases
        for qual, fn, cls in cw.defs_with_qualnames(tree):
            kind = classify(qual, fn, cls, bases, ui_module, app_module)
            params, returns = cw.signature(fn)
            word = cls if fn.name == "__init__" and cls else fn.name
            rows.append({"qualname": qual, "file": rel, "line": fn.lineno, "kind": kind,
                         "flow": None if kind in ("ui", "handler", "app") else flow_of(rel),
                         "class": cls, "params": params, "returns": returns,
                         "doc": (ast.get_docstring(fn) or "").strip().split("\n")[0][:160],
                         "tests": words.get(word, 0), "lines": (fn.end_lineno or fn.lineno) - fn.lineno + 1})
    return rows, failed


def render(rows, failed, ref):
    by_kind = Counter(r["kind"] for r in rows)
    flows = defaultdict(Counter)
    for r in rows:
        if r["flow"]:
            flows[r["flow"]][r["kind"]] += 1
            flows[r["flow"]]["untested_candidate"] += r["kind"] == "candidate" and r["tests"] == 0
    out = [f"# Code-Wire inventory — {ref}", "",
           f"- defs: {len(rows)} · " + " · ".join(f"{k} {by_kind[k]}" for k in KINDS),
           f"- files that failed to parse: {len(failed)}", "",
           "## By flow (domain map)", "", "| flow | candidate | private | trivial | candidate named by no test |", "|---|---|---|---|---|"]
    for f in sorted(flows, key=lambda x: int(x[1:])):
        c = flows[f]
        out.append(f"| {f} {FLOW_NAMES[f]} | {c['candidate']} | {c['private']} | {c['trivial']} | {c['untested_candidate']} |")
    nf = Counter(r["kind"] for r in rows if r["kind"] in ("candidate", "private", "trivial") and not r["flow"])
    out += ["", f"Domain defs with no flow (module not in FLOWS): {sum(nf.values())}", "",
            "## UI (high-level map)", "",
            f"- App class `{APP_CLASS}`: {by_kind['app']} orchestration methods (flow decided by hand), {by_kind['handler']} handlers",
            f"- UI defs in widgets/screens/presentation: {by_kind['ui']}", "", "| UI module | defs |", "|---|---|"]
    for f, n in Counter(r["file"] for r in rows if r["kind"] == "ui").most_common():
        out.append(f"| `{f}` | {n} |")
    out += ["", "## Candidates per flow", ""]
    for f in sorted(flows, key=lambda x: int(x[1:])):
        out.append(f"### {f} {FLOW_NAMES[f]}")
        out += [f"- `{r['qualname']}` ({r['file']}:{r['line']}, tests {r['tests']})"
                for r in rows if r["flow"] == f and r["kind"] == "candidate"]
        out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--ref", default="", help="commit the worktree is on, for the report header")
    a = ap.parse_args(argv)
    rows, failed = inventory(a.repo)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "inventory.json").write_text(json.dumps({"ref": a.ref, "failed": failed, "defs": rows}, indent=1), encoding="utf-8")
    (a.out / "inventory.md").write_text(render(rows, failed, a.ref), encoding="utf-8")
    print(f"{len(rows)} defs -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
