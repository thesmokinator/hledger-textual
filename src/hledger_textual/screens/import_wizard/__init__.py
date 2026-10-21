"""Multi-step wizard for creating and editing CSV import rules files."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Input, Select, Static, TextArea

from hledger_textual.csv_import import (
    auto_detect_field_mapping,
    detect_date_format,
    detect_header_row,
    detect_separator,
    generate_rules_content,
    get_rules_dir,
    read_csv_preview,
    save_rules_file,
    validate_rules_content,
)
from hledger_textual.hledger import HledgerError, load_accounts
from hledger_textual.models import CsvRulesFile
from hledger_textual.screens._dirty_guard import DirtyGuardMixin
from hledger_textual.screens.import_wizard.state import WizardState
from hledger_textual.screens.import_wizard.step_mapping import MappingStep
from hledger_textual.screens.import_wizard.step_preview import (
    SEPARATOR_OPTIONS,
    PreviewStep,
)
from hledger_textual.screens.import_wizard.step_review import ReviewStep
from hledger_textual.screens.import_wizard.step_rules import RulesStep
from hledger_textual.screens.import_wizard.step_settings import SettingsStep
from hledger_textual.widgets.autocomplete_input import AutocompleteInput

TOTAL_STEPS = 5


class ImportWizardScreen(DirtyGuardMixin, ModalScreen[tuple[Path, Path] | None]):
    """Five-step wizard for creating or editing a CSV import rules file.

    Returns ``(csv_path, rules_path)`` on success, or ``None`` on cancel.
    Implemented as a ``ModalScreen`` composing one widget per step
    (see the ``step_*`` modules), toggled via ``display``.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        csv_path: Path,
        journal_file: Path,
        existing_rules: CsvRulesFile | None = None,
    ) -> None:
        """Initialize the wizard.

        Args:
            csv_path: Path to the CSV file to import.
            journal_file: Path to the main journal file.
            existing_rules: Pre-existing rules to edit, or ``None`` for new.
        """
        super().__init__()
        self.state = WizardState(
            csv_path=csv_path,
            journal_file=journal_file,
            existing_rules=existing_rules,
        )

    def compose(self) -> ComposeResult:
        """Create the wizard layout with all 5 steps."""
        with Vertical(id="import-wizard-dialog"):
            yield Static("Import CSV - Step 1 of 5", id="wizard-step-indicator")
            yield PreviewStep(self.state)
            yield MappingStep(self.state)
            yield SettingsStep(self.state)
            yield RulesStep(self.state)
            yield ReviewStep(self.state)

            yield Static("* required", classes="form-required-footer")

            # --- Navigation ---
            with Horizontal(id="wizard-nav-buttons"):
                yield Button("Cancel", variant="default", id="btn-wizard-cancel")
                yield Button("\u2190 Back", variant="default", id="btn-wizard-back")
                yield Button("Next \u2192", variant="primary", id="btn-wizard-next")
                yield Button(
                    "Save & Continue",
                    variant="success",
                    id="btn-wizard-save",
                )

    async def on_mount(self) -> None:
        """Initialize the wizard with auto-detected values."""
        # Load accounts for autocomplete
        try:
            self.state.accounts = load_accounts(self.state.journal_file)
        except HledgerError:
            self.state.accounts = []

        account1_input = self.query_one("#wizard-account1", AutocompleteInput)
        account1_input.suggester = SuggestFromList(self.state.accounts, case_sensitive=False)

        # If editing existing rules, populate from them
        if self.state.existing_rules:
            await self._init_from_existing()
        else:
            await self._init_auto_detect()

        self._show_step(0)
        self.call_after_refresh(self.capture_initial_state)

    async def _init_auto_detect(self) -> None:
        """Auto-detect CSV properties and populate initial values."""
        self.state.separator = detect_separator(self.state.csv_path)
        self.state.has_header, self.state.column_names = detect_header_row(
            self.state.csv_path, self.state.separator
        )
        skip = 1 if self.state.has_header else 0
        self.state.sample_rows = read_csv_preview(
            self.state.csv_path, self.state.separator, skip=skip, max_rows=10
        )
        self.state.field_mapping = auto_detect_field_mapping(
            self.state.column_names, self.state.sample_rows
        )

        # Detect date format from samples
        date_col = None
        for idx, field in enumerate(self.state.field_mapping):
            if field == "date":
                date_col = idx
                break
        if date_col is not None:
            date_samples = [
                row[date_col]
                for row in self.state.sample_rows
                if date_col < len(row)
            ]
            self.state.date_format = detect_date_format(date_samples)

        # Set UI values
        self._set_separator_select(self.state.separator)
        self.query_one("#wizard-header", Select).value = (
            "yes" if self.state.has_header else "no"
        )
        self.query_one("#wizard-date-format", Input).value = self.state.date_format
        self._populate_csv_preview()
        await self._populate_mapping()

    async def _init_from_existing(self) -> None:
        """Populate wizard from an existing rules file."""
        r = self.state.existing_rules
        assert r is not None

        self.state.separator = r.separator
        skip = r.skip
        self.state.has_header = skip > 0
        _, self.state.column_names = detect_header_row(self.state.csv_path, self.state.separator)
        if not self.state.has_header:
            # Generate generic column names matching field count
            count = max(len(r.field_mapping), len(self.state.column_names))
            self.state.column_names = [f"Col {i + 1}" for i in range(count)]
        self.state.sample_rows = read_csv_preview(
            self.state.csv_path, self.state.separator, skip=skip, max_rows=10
        )
        self.state.field_mapping = r.field_mapping
        # Pad if columns don't match
        while len(self.state.field_mapping) < len(self.state.column_names):
            self.state.field_mapping.append("")
        self.state.date_format = r.date_format

        self._set_separator_select(self.state.separator)
        self.query_one("#wizard-header", Select).value = (
            "yes" if self.state.has_header else "no"
        )
        self.query_one("#wizard-rules-name", Input).value = r.name
        self.query_one("#wizard-account1", AutocompleteInput).value = r.account1
        self.query_one("#wizard-currency", Input).value = r.currency
        self.query_one("#wizard-date-format", Input).value = r.date_format

        self._populate_csv_preview()
        await self._populate_mapping()

        # Populate conditional rules
        for pattern, acct2 in r.conditional_rules:
            self._add_conditional_rule(pattern, acct2)

    def _set_separator_select(self, sep: str) -> None:
        """Set the separator Select to match the given separator."""
        select = self.query_one("#wizard-separator", Select)
        for _, val in SEPARATOR_OPTIONS:
            if val == sep:
                select.value = val
                return
        select.value = ","

    def _populate_csv_preview(self) -> None:
        """Fill the CSV preview DataTable (delegates to the preview step)."""
        self.query_one(PreviewStep).populate_preview()

    async def _populate_mapping(self) -> None:
        """Build the column mapping widgets (delegates to the mapping step)."""
        await self.query_one(MappingStep).populate_mapping()

    def _add_conditional_rule(
        self, pattern: str = "", account2: str = ""
    ) -> None:
        """Add a conditional rule row to step 3 (delegates to the rules step)."""
        self.query_one(RulesStep).add_conditional_rule(pattern, account2)

    def _remove_last_conditional_rule(self) -> None:
        """Remove the last conditional rule row."""
        if not self.query_one(RulesStep).remove_last_conditional_rule():
            self.notify("No rules to remove", severity="warning", timeout=3)

    # ------------------------------------------------------------------
    # Step navigation
    # ------------------------------------------------------------------

    def _show_step(self, step: int) -> None:
        """Show only the container for the given step."""
        self.state.current_step = step
        for i in range(TOTAL_STEPS):
            widget = self.query_one(f"#wizard-step-{i}")
            widget.display = i == step

        # Update indicator
        self.query_one("#wizard-step-indicator", Static).update(
            f"Import CSV - Step {step + 1} of {TOTAL_STEPS}"
        )

        # Show/hide nav buttons
        self.query_one("#btn-wizard-back").display = step > 0
        self.query_one("#btn-wizard-next").display = step < TOTAL_STEPS - 1
        self.query_one("#btn-wizard-save").display = step == TOTAL_STEPS - 1

        # Prepare step-specific content
        if step == 4:
            self._generate_raw_preview()

    def _generate_raw_preview(self) -> None:
        """Generate rules content and show in the TextArea."""
        content = self._build_rules_content()
        editor = self.query_one("#wizard-raw-editor", TextArea)
        editor.text = content

    def _build_rules_content(self) -> str:
        """Build rules file content from current wizard state."""
        name = self.query_one("#wizard-rules-name", Input).value.strip()
        account1 = self.query_one("#wizard-account1", AutocompleteInput).value.strip()
        currency = self.query_one("#wizard-currency", Input).value.strip()
        date_format = self.query_one("#wizard-date-format", Input).value.strip()

        separator = self.query_one("#wizard-separator", Select).value
        if separator == Select.BLANK:
            separator = ","

        has_header = self.query_one("#wizard-header", Select).value == "yes"
        skip = 1 if has_header else 0

        # Collect field mapping from selects
        field_mapping: list[str] = []
        for i in range(len(self.state.column_names)):
            try:
                sel = self.query_one(f"#mapping-select-{i}", Select)
                val = sel.value
                field_mapping.append(val if val != Select.BLANK else "")
            except Exception:
                field_mapping.append("")

        # Collect conditional rules
        cond_rules: list[tuple[str, str]] = []
        for i in range(self.state.conditional_rule_count):
            try:
                pattern = self.query_one(f"#cond-pattern-{i}", Input).value.strip()
                acct = self.query_one(f"#cond-account-{i}", AutocompleteInput).value.strip()
                if pattern and acct:
                    cond_rules.append((pattern, acct))
            except Exception:
                continue

        return generate_rules_content(
            name=name or "Unnamed",
            separator=str(separator),
            date_format=date_format,
            skip=skip,
            field_mapping=field_mapping,
            currency=currency,
            account1=account1,
            conditional_rules=cond_rules,
        )

    # ------------------------------------------------------------------
    # Validation per step
    # ------------------------------------------------------------------

    def _validate_current_step(self) -> bool:
        """Validate the current step. Returns True if valid."""
        if self.state.current_step == 1:
            return self._validate_mapping()
        if self.state.current_step == 2:
            return self._validate_settings()
        return True

    def _validate_mapping(self) -> bool:
        """Validate that at least date and amount (or amount-in) are mapped."""
        has_date = False
        has_amount = False
        has_amount_in = False

        for i in range(len(self.state.column_names)):
            try:
                sel = self.query_one(f"#mapping-select-{i}", Select)
                val = sel.value
            except Exception:
                continue
            if val == "date":
                has_date = True
            elif val == "amount":
                has_amount = True
            elif val == "amount-in":
                has_amount_in = True

        if not has_date:
            self.notify(
                "Please map at least one column to 'date'",
                severity="error", timeout=5,
            )
            return False
        if not has_amount and not has_amount_in:
            self.notify(
                "Please map at least one column to 'amount' or 'amount-in'",
                severity="error", timeout=5,
            )
            return False
        return True

    def _validate_settings(self) -> bool:
        """Validate required settings fields."""
        name = self.query_one("#wizard-rules-name", Input).value.strip()
        account1 = self.query_one("#wizard-account1", AutocompleteInput).value.strip()
        if not name:
            self.notify("Rules name is required", severity="error", timeout=3)
            return False
        if not account1:
            self.notify("Bank account is required", severity="error", timeout=3)
            return False
        return True

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        match event.button.id:
            case "btn-wizard-cancel":
                self.action_cancel()
            case "btn-wizard-back":
                if self.state.current_step > 0:
                    self._show_step(self.state.current_step - 1)
            case "btn-wizard-next":
                if self._validate_current_step():
                    self._show_step(self.state.current_step + 1)
            case "btn-wizard-save":
                self._do_save()
            case "btn-wizard-add-rule":
                self._add_conditional_rule()
            case "btn-wizard-remove-rule":
                self._remove_last_conditional_rule()

    @on(Select.Changed, "#wizard-separator")
    async def _on_separator_changed(self, event: Select.Changed) -> None:
        """Re-detect headers and reload preview when separator changes."""
        sep = str(event.value) if event.value != Select.BLANK else ","
        self.state.separator = sep
        self.state.has_header, self.state.column_names = detect_header_row(
            self.state.csv_path, self.state.separator
        )
        skip = 1 if self.state.has_header else 0
        self.state.sample_rows = read_csv_preview(
            self.state.csv_path, self.state.separator, skip=skip, max_rows=10
        )
        self.state.field_mapping = auto_detect_field_mapping(
            self.state.column_names, self.state.sample_rows
        )
        self.query_one("#wizard-header", Select).value = (
            "yes" if self.state.has_header else "no"
        )
        self._populate_csv_preview()
        await self._populate_mapping()

    @on(Select.Changed, "#wizard-header")
    async def _on_header_changed(self, event: Select.Changed) -> None:
        """Reload preview when header setting changes."""
        self.state.has_header = event.value == "yes"
        skip = 1 if self.state.has_header else 0
        if not self.state.has_header:
            # Re-detect without header
            self.state.column_names = [f"Col {i + 1}" for i in range(
                len(self.state.column_names) if self.state.column_names else 1
            )]
        else:
            _, self.state.column_names = detect_header_row(
                self.state.csv_path, self.state.separator
            )
        self.state.sample_rows = read_csv_preview(
            self.state.csv_path, self.state.separator, skip=skip, max_rows=10
        )
        self.state.field_mapping = auto_detect_field_mapping(
            self.state.column_names, self.state.sample_rows
        )
        self._populate_csv_preview()
        await self._populate_mapping()

    def _do_save(self) -> None:
        """Save the rules file and dismiss with paths."""
        editor = self.query_one("#wizard-raw-editor", TextArea)
        content = editor.text

        # Validate with hledger dry-run
        error = validate_rules_content(self.state.csv_path, content)
        if error:
            self.notify(
                f"Rules validation failed: {error}",
                severity="error",
                timeout=8,
            )
            return

        name = self.query_one("#wizard-rules-name", Input).value.strip() or "Unnamed"
        rules_dir = get_rules_dir(self.state.journal_file)
        rules_path = save_rules_file(rules_dir, name, content)

        self.dismiss((self.state.csv_path, rules_path))



