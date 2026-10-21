"""Tests for the shared FormScreenBase class."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input

from hledger_textual.screens._dirty_guard import DirtyGuardMixin
from hledger_textual.screens.account_note_form import AccountNoteModal
from hledger_textual.screens.budget_form import BudgetFormScreen
from hledger_textual.screens.custom_report_form import CustomReportFormScreen
from hledger_textual.screens.form_base import FormScreenBase
from hledger_textual.screens.recurring_form import RecurringFormScreen
from hledger_textual.screens.transaction_form import TransactionFormScreen

FORM_SCREENS = [
    TransactionFormScreen,
    RecurringFormScreen,
    CustomReportFormScreen,
    BudgetFormScreen,
    AccountNoteModal,
]


class _DummyForm(FormScreenBase[str | None]):
    """Minimal form used to exercise the base class routing."""

    def __init__(self) -> None:
        super().__init__()
        self.saved = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(id="dummy-input")
            yield Button("Save", id="btn-save")
            yield Button("Cancel", id="btn-form-cancel")

    def _save(self) -> None:
        self.saved = True
        self.dismiss("saved")


class _GuardedDummyForm(DirtyGuardMixin, FormScreenBase[str | None]):
    """Dummy form combining the dirty guard with the base class."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(id="dummy-input")
            yield Button("Save", id="btn-save")
            yield Button("Cancel", id="btn-form-cancel")

    def _save(self) -> None:
        self.dismiss("saved")


class _DummyApp(App[None]):
    """App that pushes a single form screen."""

    def __init__(self, screen: FormScreenBase) -> None:
        super().__init__()
        self._screen = screen
        self.result: object = "unset"

    def on_mount(self) -> None:
        self.push_screen(self._screen, callback=self._store)

    def _store(self, result: object) -> None:
        self.result = result


@pytest.mark.parametrize("form_cls", FORM_SCREENS)
def test_all_forms_inherit_form_screen_base(form_cls):
    """Every migrated form screen inherits from FormScreenBase."""
    assert issubclass(form_cls, FormScreenBase)


def test_button_ids_are_configured_per_form():
    """Save/cancel button ids match the ids used in each form's compose."""
    assert TransactionFormScreen.SAVE_BUTTON_ID == "btn-save"
    assert CustomReportFormScreen.SAVE_BUTTON_ID == "btn-custom-report-save"
    assert CustomReportFormScreen.CANCEL_BUTTON_ID == "btn-custom-report-cancel"
    assert BudgetFormScreen.SAVE_BUTTON_ID == "btn-budget-save"
    assert AccountNoteModal.SAVE_BUTTON_ID == "btn-note-save"


def test_base_class_defines_escape_binding():
    """The base class provides the Escape-to-cancel binding."""
    keys = [(b.key, b.action) for b in FormScreenBase.BINDINGS]
    assert ("escape", "cancel") in keys


def test_dirty_guard_cancel_takes_precedence_over_base():
    """DirtyGuardMixin.action_cancel wins over the base implementation."""
    assert _GuardedDummyForm.action_cancel is DirtyGuardMixin.action_cancel


async def test_save_button_calls_save_and_dismisses():
    """Pressing Save routes to _save and dismisses with its result."""
    screen = _DummyForm()
    app = _DummyApp(screen)
    async with app.run_test() as pilot:
        await pilot.click("#btn-save")
        await pilot.pause()
    assert screen.saved
    assert app.result == "saved"


async def test_cancel_button_dismisses_with_none():
    """Pressing Cancel dismisses with None."""
    app = _DummyApp(_DummyForm())
    async with app.run_test() as pilot:
        await pilot.click("#btn-form-cancel")
        await pilot.pause()
    assert app.result is None


async def test_escape_dismisses_with_none():
    """Escape triggers the base cancel action."""
    app = _DummyApp(_DummyForm())
    async with app.run_test() as pilot:
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


class _ExtraButtonForm(DirtyGuardMixin, FormScreenBase[str | None]):
    """Guarded form with an extra button handled via the base hook."""

    def __init__(self) -> None:
        super().__init__()
        self.extra_presses = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(id="dummy-input")
            yield Button("Extra", id="btn-extra")
            yield Button("Save", id="btn-save")
            yield Button("Cancel", id="btn-form-cancel")

    def _on_extra_button(self, event) -> bool:
        if event.button.id == "btn-extra":
            self.extra_presses += 1
            return True
        return False

    def _save(self) -> None:
        self.dismiss("saved")


async def test_extra_button_and_single_cancel_dispatch():
    """Extra buttons run once; a dirty Cancel click warns instead of closing.

    Regression test: overriding ``on_button_pressed`` and calling ``super()``
    would run the routing twice under Textual's per-class dispatch, so the
    second call would discard the guarded form.
    """
    screen = _ExtraButtonForm()
    app = _DummyApp(screen)
    async with app.run_test() as pilot:
        screen.capture_initial_state()
        await pilot.click("#btn-extra")
        await pilot.pause()
        assert screen.extra_presses == 1
        app.screen.query_one("#dummy-input", Input).value = "changed"
        await pilot.click("#btn-form-cancel")
        await pilot.pause()
        assert app.result == "unset"
        assert screen._discard_armed is True


async def test_guarded_form_warns_before_discarding_changes():
    """A dirty guarded form does not dismiss on the first Escape."""
    screen = _GuardedDummyForm()
    app = _DummyApp(screen)
    async with app.run_test() as pilot:
        screen.capture_initial_state()
        app.screen.query_one("#dummy-input", Input).value = "changed"
        await pilot.press("escape")
        await pilot.pause()
        assert app.result == "unset"
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None
