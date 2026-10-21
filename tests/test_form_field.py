"""Tests for the FormField widget."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label

from hledger_textual.screens.budget_form import BudgetFormScreen
from hledger_textual.screens.custom_report_form import CustomReportFormScreen
from hledger_textual.screens.recurring_form import RecurringFormScreen
from hledger_textual.screens.transaction_form import TransactionFormScreen
from hledger_textual.widgets.form_field import FormField


class _FieldApp(App[None]):
    """App hosting a few FormField rows."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield FormField("Date:", Input(id="field-date"), required=True)
            yield FormField("Code:", Input(id="field-code"), optional=True)
            yield FormField("Status:", Input(id="field-status"))
            yield FormField("Expression:", Input(id="field-expr"), required=True, id="expr-row")


async def test_required_field_appends_asterisk_and_class():
    """Required fields render ``label*`` and carry the required class."""
    app = _FieldApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        field = app.query(FormField)[0]
        assert "form-field" in field.classes
        assert "form-field--required" in field.classes
        assert field.query_one(Label).renderable == "Date:*"


async def test_optional_and_plain_field_classes():
    """Optional fields get the optional class; plain fields get neither."""
    app = _FieldApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        fields = list(app.query(FormField))
        assert "form-field--optional" in fields[1].classes
        assert fields[1].query_one(Label).renderable == "Code:"
        assert "form-field--required" not in fields[2].classes
        assert "form-field--optional" not in fields[2].classes


async def test_child_is_queryable_and_row_id_is_preserved():
    """The child keeps its id and the row keeps the id passed to FormField."""
    app = _FieldApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#field-date", Input) is not None
        assert app.query_one("#expr-row", FormField) is not None


async def test_label_already_starred_is_not_doubled():
    """A label already ending with ``*`` is not starred twice."""
    field = FormField("Date:*", Input(), required=True)
    assert field._label_text == "Date:*"


def test_migrated_forms_use_form_field():
    """The migrated form modules compose with FormField, not raw rows."""
    import inspect

    for form in (TransactionFormScreen, RecurringFormScreen, BudgetFormScreen, CustomReportFormScreen):
        assert "FormField(" in inspect.getsource(form.compose), form.__name__
