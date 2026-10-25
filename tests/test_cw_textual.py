"""Tests for the Textual adapter (A2b).

Why these matter: in the spike of part 41, every event after the Load dialog had no root until the
recorder followed `call_after_refresh`. In a Textual app most user actions reach a node through a
hand-off: a message, a dialog and its callback, a worker, a later call. If the root does not cross the
hand-off, the node is filed under the wrong entry point or under `harness`, and the matrix of part 41
shows a bug (a path that stops) where there is none, or hides one. The screen channel is the other half:
in a UI the observable truth is what the screen shows, not the return value (MF-3).
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

textual = pytest.importorskip("textual")
from textual.app import App  # noqa: E402
from textual.message import Message  # noqa: E402
from textual.screen import ModalScreen  # noqa: E402
from textual.widgets import Button, Static  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import codewire_events as events  # noqa: E402
import cw_record_plugin as rec  # noqa: E402
import cw_textual  # noqa: E402

REPO = os.path.normcase(str(Path(__file__).resolve().parents[1]))


def node(name):
    return rec.wrap({"name": name, "modify": []}, lambda value=None: value)


parse = node("parse")
apply_ = node("apply")
paint = node("paint")
tick = node("tick")
post_go = rec.wrap({"name": "post_go", "modify": []}, lambda app: app.post_message(app.Go()) and "posted")


class Dialog(ModalScreen):
    def compose(self):
        yield Button("ok", id="ok")

    def on_button_pressed(self, event):
        parse("in the dialog")        # a handler of the dialog: the root of the opener
        self.dismiss("P1")


class Demo(App):
    BINDINGS = [("o", "open", "open"), ("w", "work", "work"), ("t", "time", "time")]

    class Go(Message):
        pass

    def compose(self):
        yield Button("go", id="go")
        yield Static("idle", id="status")

    def on_button_pressed(self, event):
        post_go(self)                   # a node that posts a message: the parent of the handler's nodes

    def on_demo_go(self, message):
        apply_("from the message")
        self.query_one("#status", Static).update("applied")
        self.notify("done")
        paint("after the paint")
        parse("after the notice")

    def action_open(self):
        self.push_screen(Dialog(), self.done)

    def done(self, value):
        self.call_after_refresh(self.later, value)

    def later(self, value):
        parse(value)

    def action_work(self):
        self.run_worker(self.job, thread=True)

    def job(self):
        self.call_from_thread(self.back)

    def back(self):
        apply_("from the worker")

    def action_time(self):
        self.set_timer(0.01, self.ring)

    def ring(self):
        tick("rang")


@pytest.fixture(autouse=True)
def adapter(monkeypatch):
    monkeypatch.setenv("CW_UI", "#status")
    events.ROOT_DIR[0] = REPO
    events.EVENTS.clear()
    rec.TRACE.clear()
    rec.KEPT.clear()
    cw_textual.install()
    yield
    cw_textual.uninstall()


def run(script):
    async def main():
        app = Demo()
        async with app.run_test() as pilot:
            await script(app, pilot)
            for _ in range(5):
                await pilot.pause(0.02)
                await app.workers.wait_for_complete()
    asyncio.run(main())
    return {(e["node"], e["in"].get("value")): e for e in events.EVENTS}


def test_a_message_keeps_the_root_and_the_parent_of_the_poster():
    async def script(app, pilot):
        await pilot.click("#go")
    ev = run(script)
    poster = next(e for e in events.EVENTS if e["node"] == "post_go")
    assert poster["root"] == "Demo.on_button_pressed" and poster["out"] == "posted"
    handled = ev[("apply", "from the message")]
    # with no adapter the root would be Demo.on_demo_go and the parent ENTRY
    assert handled["root"] == "Demo.on_button_pressed" and handled["parent"] == "post_go"


def test_a_dialog_and_its_callback_keep_the_root_of_the_opener():
    async def script(app, pilot):
        await pilot.press("o")
        await pilot.pause()
        await pilot.click("#ok")
    ev = run(script)
    assert ev[("parse", "in the dialog")]["root"] == "Demo.action_open"   # not Dialog.on_button_pressed
    # dismiss -> callback -> call_after_refresh -> later: three hand-offs, one root
    assert ev[("parse", "P1")]["root"] == "Demo.action_open"


def test_a_worker_and_call_from_thread_keep_the_root():
    async def script(app, pilot):
        await pilot.press("w")
    ev = run(script)
    assert ev[("apply", "from the worker")]["root"] == "Demo.action_work"


def test_a_timer_keeps_the_root():
    async def script(app, pilot):
        await pilot.press("t")
        await pilot.pause(0.1)
    ev = run(script)
    assert ev[("tick", "rang")]["root"] == "Demo.action_time"


def test_the_screen_channel_holds_what_the_user_sees():
    async def script(app, pilot):
        await pilot.click("#go")
    ev = run(script)
    ui = ev[("paint", "after the paint")]["ui"]
    assert ui["#status"] == "applied" and ui["screen"] == "Screen" and ui["stack"] == 1
    assert ui["focused"] == "Button#go"   # focus is app state: CW-U-2 was the focus on the wrong widget
    assert ui["notices"] == [{"severity": "information", "message": "done"}]
    # a notice goes to the next event only: not to the one before it, not again to the one after it
    assert "notices" not in ev[("apply", "from the message")]["ui"]
    assert "notices" not in ev[("parse", "after the notice")]["ui"]


def test_a_direct_call_in_the_app_is_still_the_harness():
    async def script(app, pilot):
        app.later("direct")            # what the app tests do: call the handler, not the key
    ev = run(script)
    assert ev[("parse", "direct")]["root"] == events.HARNESS


def test_uninstall_gives_back_textual():
    from textual.message_pump import MessagePump
    cw_textual.uninstall()
    assert "cw_textual" not in getattr(MessagePump.post_message, "__module__", "")
    assert cw_textual.snapshot not in events.EXTRAS
