"""Code-Wire adapter for Textual: the root and the parent of a call cross the hand-offs of the framework.

In a Textual app, a user action often reaches a node through a hand-off that breaks the Python stack:
a message (`post_message` -> `on_*`), a dialog (`push_screen` -> the dialog's handlers -> its callback),
a worker (`run_worker`, `call_from_thread`) or a later call (`call_after_refresh`, `call_later`,
`call_next`, `set_timer`). With no adapter, each node after a hand-off gets a new root or `harness`.

`install()` patches these methods so that each hand-off carries the context of the code that made it:
a message and a dialog screen get a stamp, and a callback runs inside `codewire_events.carry()`.

The screen channel (MF-3): each event of a node also gets `ui`, the state that the user sees after the
call: the screen class, the depth of the screen stack, the focused widget, and the text of the widgets
in `CW_UI` (CSS selectors, separated by commas). `App.notify` adds each notice to the next event.

    CW_ADAPTERS=textual  turns this adapter on in the pytest plugin
    CW_UI                for example `#status_text,#log_line_1`
"""
import os
import sys

import codewire_events as events

PATCHED = []
NOTICES = []


def _ctx(depth=2):
    return events.here(sys._getframe(depth))


def _carry(fn, ctx):
    return events.carry(fn, ctx) if ctx and callable(fn) else fn


def _widget_id(w):
    if w is None:
        return None
    return f"{type(w).__name__}#{w.id}" if getattr(w, "id", None) else type(w).__name__


def _text(widget):
    try:
        r = widget.render()
        return str(getattr(r, "plain", r))
    except Exception as exc:  # noqa: BLE001 (a channel must not break the app)
        return f"<render failed: {type(exc).__name__}>"


def snapshot(ev):
    """Add the `ui` field: what the user sees after the call."""
    try:
        from textual._context import active_app
        app = active_app.get()
    except (LookupError, ImportError):
        return
    ui = {"screen": type(app.screen).__name__, "stack": len(app.screen_stack), "focused": _widget_id(app.focused)}
    for sel in [s.strip() for s in os.environ.get("CW_UI", "").split(",") if s.strip()]:
        try:
            ui[sel] = _text(app.query_one(sel))
        except Exception:  # noqa: BLE001
            ui[sel] = None
    if NOTICES:
        ui["notices"] = NOTICES[:]
        NOTICES.clear()
    ev["ui"] = ui


def install():
    """Patch Textual one time. Returns False when Textual is not installed."""
    if PATCHED:
        return True
    try:
        from textual.app import App
        from textual.message_pump import MessagePump
    except ImportError:
        return False

    def patch(owner, name, make):
        orig = getattr(owner, name)
        setattr(owner, name, make(orig))
        PATCHED.append((owner, name, orig))

    def post_message(orig):
        def w(self, message):
            ctx = _ctx()
            if ctx and "_cw_ctx" not in getattr(message, "__dict__", {}):
                events.stamp(message, ctx)
            return orig(self, message)
        return w

    def push_screen(orig):
        def w(self, screen, callback=None, *a, **k):
            ctx = _ctx()
            if ctx and not isinstance(screen, str):
                events.stamp(screen, ctx)   # the dialog's own handlers keep the opener's root
            return orig(self, screen, _carry(callback, ctx), *a, **k)
        return w

    def later(orig):   # call_after_refresh, call_later, call_next, call_from_thread
        def w(self, callback, *a, **k):
            return orig(self, _carry(callback, _ctx()), *a, **k)
        return w

    def set_timer(orig):
        def w(self, delay, callback=None, *a, **k):
            return orig(self, delay, _carry(callback, _ctx()), *a, **k)
        return w

    def run_worker(orig):
        def w(self, work, *a, **k):
            if callable(work) and not hasattr(work, "__await__"):
                work = _carry(work, _ctx())
            return orig(self, work, *a, **k)
        return w

    def notify(orig):
        def w(self, message, *a, **k):
            NOTICES.append({"severity": k.get("severity", "information"), "message": str(message)})
            return orig(self, message, *a, **k)
        return w

    patch(MessagePump, "post_message", post_message)
    patch(App, "push_screen", push_screen)
    for name in ("call_after_refresh", "call_later", "call_next"):
        patch(MessagePump, name, later)
    patch(App, "call_from_thread", later)
    patch(MessagePump, "set_timer", set_timer)
    patch(App, "run_worker", run_worker)
    patch(App, "notify", notify)
    events.EXTRAS.append(snapshot)
    return True


def uninstall():
    while PATCHED:
        owner, name, orig = PATCHED.pop()
        setattr(owner, name, orig)
    if snapshot in events.EXTRAS:
        events.EXTRAS.remove(snapshot)
    NOTICES.clear()
