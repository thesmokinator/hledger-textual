"""Per-step tests for the decomposed CSV import wizard.

Each step widget is mounted on its own with a shared
:class:`WizardState`, without the hledger binary.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Select, Static, TextArea

from hledger_textual.screens.import_wizard.state import WizardState
from hledger_textual.screens.import_wizard.step_mapping import MappingStep
from hledger_textual.screens.import_wizard.step_preview import PreviewStep
from hledger_textual.screens.import_wizard.step_review import ReviewStep
from hledger_textual.screens.import_wizard.step_rules import RulesStep
from hledger_textual.screens.import_wizard.step_settings import SettingsStep


def _state(tmp_path: Path, **overrides) -> WizardState:
    state = WizardState(
        csv_path=tmp_path / "bank.csv",
        journal_file=tmp_path / "main.journal",
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


class _StepApp(App[None]):
    """App hosting a single wizard step."""

    def __init__(self, step) -> None:
        super().__init__()
        self._step = step

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self._step


def test_wizard_state_defaults(tmp_path):
    """WizardState carries the documented defaults."""
    state = _state(tmp_path)
    assert state.current_step == 0
    assert state.separator == ","
    assert state.has_header is True
    assert state.date_format == "%Y-%m-%d"
    assert state.conditional_rule_count == 0


async def test_preview_step_populates_table(tmp_path):
    """The preview step fills its table from the shared state."""
    state = _state(
        tmp_path,
        column_names=["Date", "Amount"],
        sample_rows=[["2026-01-01", "10.00"], ["2026-01-02", "20.00"]],
    )
    app = _StepApp(PreviewStep(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(PreviewStep).populate_preview()
        await pilot.pause()
        table = app.query_one("#wizard-csv-preview", DataTable)
        assert table.row_count == 2
        assert app.query_one("#wizard-separator", Select) is not None


async def test_mapping_step_builds_select_per_column(tmp_path):
    """The mapping step builds one Select per column with its initial value."""
    state = _state(
        tmp_path,
        column_names=["Date", "Amount"],
        sample_rows=[["2026-01-01", "10.00"]],
        field_mapping=["date", "amount"],
    )
    step = MappingStep(state)
    app = _StepApp(step)
    async with app.run_test() as pilot:
        await pilot.pause()
        await step.populate_mapping()
        await pilot.pause()
        assert app.query_one("#mapping-select-0", Select).value == "date"
        assert app.query_one("#mapping-select-1", Select).value == "amount"


async def test_settings_step_has_all_inputs(tmp_path):
    """The settings step composes the four settings inputs."""
    app = _StepApp(SettingsStep(_state(tmp_path)))
    async with app.run_test() as pilot:
        await pilot.pause()
        for widget_id in (
            "#wizard-rules-name",
            "#wizard-account1",
            "#wizard-currency",
            "#wizard-date-format",
        ):
            assert app.query_one(widget_id, Input) is not None


async def test_rules_step_add_and_remove(tmp_path):
    """Adding and removing rules updates the shared state counter."""
    state = _state(tmp_path, accounts=["expenses:food"])
    step = RulesStep(state)
    app = _StepApp(step)
    async with app.run_test() as pilot:
        await pilot.pause()
        step.add_conditional_rule("grocery", "expenses:food")
        await pilot.pause()
        assert state.conditional_rule_count == 1
        assert app.query_one("#cond-pattern-0", Input).value == "grocery"

        assert step.remove_last_conditional_rule() is True
        await pilot.pause()
        assert state.conditional_rule_count == 0
        assert step.remove_last_conditional_rule() is False


async def test_review_step_has_editor(tmp_path):
    """The review step composes the raw rules editor."""
    app = _StepApp(ReviewStep(_state(tmp_path)))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#wizard-raw-editor", TextArea) is not None


async def test_mapping_step_shows_suggested_badges(tmp_path):
    """Auto-detected rows carry a [suggested] badge; manual rows don't."""
    state = _state(
        tmp_path,
        column_names=["Date", "Amount"],
        sample_rows=[["2026-01-01", "10.00"]],
        field_mapping=["date", "amount"],
        auto_suggested=[True, False],
    )
    step = MappingStep(state)
    app = _StepApp(step)
    async with app.run_test() as pilot:
        await pilot.pause()
        await step.populate_mapping()
        await pilot.pause()
        assert "suggested" in str(
            app.query_one("#mapping-suggested-0", Static).renderable
        )
        assert len(app.query("#mapping-suggested-1")) == 0


async def test_mapping_step_clears_badge_on_user_change(tmp_path):
    """Touching a Select clears its suggestion flag and badge."""
    state = _state(
        tmp_path,
        column_names=["Date", "Amount"],
        sample_rows=[["2026-01-01", "10.00"]],
        field_mapping=["date", "amount"],
        auto_suggested=[True, True],
    )
    step = MappingStep(state)
    app = _StepApp(step)
    async with app.run_test() as pilot:
        await pilot.pause()
        await step.populate_mapping()
        await pilot.pause()
        assert len(app.query("#mapping-suggested-0")) == 1

        app.query_one("#mapping-select-0", Select).value = "description"
        await pilot.pause()

        assert state.auto_suggested[0] is False
        assert len(app.query("#mapping-suggested-0")) == 0
        # Untouched rows keep their badge.
        assert len(app.query("#mapping-suggested-1")) == 1


async def test_mapping_step_error_line(tmp_path):
    """set_error/clear_error control the inline mapping error line."""
    step = MappingStep(_state(tmp_path))
    app = _StepApp(step)
    async with app.run_test() as pilot:
        await pilot.pause()
        step.set_error("boom")
        await pilot.pause()
        assert "boom" in str(app.query_one("#wizard-mapping-error", Static).renderable)
        step.clear_error()
        await pilot.pause()
        assert str(app.query_one("#wizard-mapping-error", Static).renderable) == ""
