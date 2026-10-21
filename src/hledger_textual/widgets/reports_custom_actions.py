"""Custom-report actions for the reports pane.

View switching, Select refresh, output rendering, and CRUD handlers for
user-defined reports, split out of ``reports_pane.py`` as a mixin. The
host pane provides the journal/custom-report state, the data loaders
(``_load_report_data`` / ``_load_custom_report_data``), the built-in
context bar, and the ``CustomReportStateChanged`` message class.
"""

from __future__ import annotations

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Select, Static

from hledger_textual.config import (
    delete_custom_report,
    load_custom_reports,
    save_custom_report,
)
from hledger_textual.models import CustomReport
from hledger_textual.widgets.empty_state import EmptyState
from hledger_textual.widgets.loading import hide_loading_overlay
from hledger_textual.widgets.reports_renderer import format_custom_output


class ReportsCustomActionsMixin:
    """Custom-report view and CRUD behaviour for :class:`ReportsPane`."""

    def _update_context_bar_custom(self, name: str, command: str) -> None:
        """Refresh the context bar to show the active custom report name and command.

        Args:
            name: The custom report name.
            command: The hledger command string.
        """
        text = Text()
        text.append(name, style="bold")
        if command:
            text.append("  ·  ", style="dim")
            text.append(command, style="dim")

        self.query_one("#report-context-bar", Static).update(text)

    # --- View toggle ---

    def _set_custom_view(self, active: bool) -> None:
        """Toggle between the built-in report view and the custom report output view.

        When ``active`` is ``True``, the DataTable and period Select are hidden
        and the raw-output area is shown.  The inverse applies when ``False``.
        A :class:`CustomReportStateChanged` message is posted so that the app
        can update the footer accordingly.

        Args:
            active: ``True`` to show the custom report output; ``False`` for the
                built-in DataTable view.
        """
        table = self.query_one("#reports-table", DataTable)
        output = self.query_one("#custom-report-output", VerticalScroll)
        period_select = self.query_one("#report-period-select", Select)
        type_select = self.query_one("#report-type-select", Select)

        output.display = active
        type_select.display = not active
        period_select.display = not active
        if active:
            table.display = False
            self.query_one("#reports-empty-state", EmptyState).display = False
        else:
            self._sync_empty_state()

        self.post_message(self.CustomReportStateChanged(active))

    # --- Custom report Select ---

    def _refresh_custom_report_select(self, select_name: str | None = None) -> None:
        """Reload custom report options in the Select widget.

        Args:
            select_name: If provided, sets the Select to this report name
                after refreshing the options.
        """
        reports = load_custom_reports()
        select = self.query_one("#custom-report-select", Select)
        options = [(name, name) for name in reports]
        select.set_options(options)
        if select_name is not None and select_name in reports:
            select.value = select_name

    # --- Period calculation ---

    def _apply_custom_output(self, output: str, command: str) -> None:
        """Display custom report output with Rich styling.

        The hledger-generated title line is suppressed because the report name
        is already shown in the context bar.

        Args:
            output: The raw text returned by hledger.
            command: The command used, forwarded to the context bar.
        """
        hide_loading_overlay(self)
        static = self.query_one("#custom-report-text", Static)
        static.update(format_custom_output(output.rstrip(), skip_title=True))
        if self._custom_report_name:
            self._update_context_bar_custom(self._custom_report_name, command)

    def action_new_custom_report(self) -> None:
        """Open the form to create a new custom report."""
        from hledger_textual.screens.custom_report_form import CustomReportFormScreen

        def _on_result(report: CustomReport | None) -> None:
            if report is None:
                return
            save_custom_report(report.name, report.command)
            self._custom_report_name = report.name
            self._refresh_custom_report_select(select_name=report.name)
            self._set_custom_view(active=True)
            self._load_custom_report_data()

        self.app.push_screen(CustomReportFormScreen(), _on_result)

    def action_edit_custom_report(self) -> None:
        """Open the form to edit the currently selected custom report."""
        if self._custom_report_name is None:
            self.notify("No custom report selected", severity="warning", timeout=3)
            return

        from hledger_textual.screens.custom_report_form import CustomReportFormScreen

        reports = load_custom_reports()
        command = reports.get(self._custom_report_name, "")
        old_name = self._custom_report_name
        report = CustomReport(name=old_name, command=command)

        def _on_result(updated: CustomReport | None) -> None:
            if updated is None:
                return
            if updated.name != old_name:
                delete_custom_report(old_name)
            save_custom_report(updated.name, updated.command)
            self._custom_report_name = updated.name
            self._refresh_custom_report_select(select_name=updated.name)
            self._update_context_bar_custom(updated.name, updated.command)
            self._load_custom_report_data()

        self.app.push_screen(CustomReportFormScreen(report=report), _on_result)

    def action_delete_custom_report(self) -> None:
        """Open a confirmation dialog to delete the currently selected custom report."""
        if self._custom_report_name is None:
            self.notify("No custom report selected", severity="warning", timeout=3)
            return

        from hledger_textual.screens.custom_report_delete_confirm import (
            CustomReportDeleteConfirmModal,
        )

        name = self._custom_report_name

        def _on_result(confirmed: bool) -> None:
            if not confirmed:
                return
            delete_custom_report(name)
            self._custom_report_name = None
            self._refresh_custom_report_select()
            self._set_custom_view(active=False)
            self._update_context_bar_builtin()
            self._load_report_data()

        self.app.push_screen(CustomReportDeleteConfirmModal(name), _on_result)

    def action_back_to_builtin(self) -> None:
        """Return from custom report view to the built-in report view."""
        if self._custom_report_name is None:
            return
        self._custom_report_name = None
        self.query_one("#custom-report-select", Select).clear()
        self._set_custom_view(active=False)
        self._update_context_bar_builtin()
        self._load_report_data()

    # --- Event handlers ---
