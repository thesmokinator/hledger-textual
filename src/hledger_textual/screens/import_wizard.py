"""Multi-step wizard for creating and editing CSV import rules files."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, DataTable, Input, Label, Select, Static, TextArea

from hledger_textual.config import load_default_commodity
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
from hledger_textual.widgets.autocomplete_input import AutocompleteInput

_SEPARATOR_OPTIONS = [
    ("Comma (,)", ","),
    ("Semicolon (;)", ";"),
    ("Tab", "\t"),
    ("Pipe (|)", "|"),
]

_HEADER_OPTIONS = [
    ("Yes", "yes"),
    ("No", "no"),
]

_FIELD_OPTIONS = [
    ("(skip)", ""),
    ("date", "date"),
    ("date2", "date2"),
    ("status", "status"),
    ("code", "code"),
    ("description", "description"),
    ("comment", "comment"),
    ("amount", "amount"),
    ("amount-in", "amount-in"),
    ("amount-out", "amount-out"),
    ("currency", "currency"),
    ("account1", "account1"),
    ("account2", "account2"),
]

TOTAL_STEPS = 5


class ImportWizardScreen(ModalScreen[tuple[Path, Path] | None]):
    """Five-step wizard for creating or editing a CSV import rules file.

    Returns ``(csv_path, rules_path)`` on success, or ``None`` on cancel.
    Implemented as a single ``ModalScreen`` with step containers toggled
    via ``display``.
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
        self.csv_path = csv_path
        self.journal_file = journal_file
        self.existing_rules = existing_rules
        self.current_step = 0
        self.accounts: list[str] = []
        self.conditional_rule_count = 0

        # Detected/configured values (populated on mount)
        self._separator = ","
        self._has_header = True
        self._column_names: list[str] = []
        self._sample_rows: list[list[str]] = []
        self._field_mapping: list[str] = []
        self._date_format = "%Y-%m-%d"

    def compose(self) -> ComposeResult:
        """Create the wizard layout with all 5 steps."""
        with Vertical(id="import-wizard-dialog"):
            yield Static("Import CSV - Step 1 of 5", id="wizard-step-indicator")

            # --- Step 0: CSV Preview ---
            with Vertical(id="wizard-step-0", classes="wizard-step"):
                yield Static("CSV Preview", classes="wizard-step-title")
                with Horizontal(classes="form-field"):
                    yield Label("Separator:")
                    yield Select(
                        options=_SEPARATOR_OPTIONS,
                        value=",",
                        id="wizard-separator",
                    )
                with Horizontal(classes="form-field"):
                    yield Label("Header row:")
                    yield Select(
                        options=_HEADER_OPTIONS,
                        value="yes",
                        id="wizard-header",
                    )
                yield DataTable(id="wizard-csv-preview")

            # --- Step 1: Column Mapping ---
            with VerticalScroll(id="wizard-step-1", classes="wizard-step"):
                yield Static("Column Mapping", classes="wizard-step-title")
                yield Static(
                    "Map each CSV column to a journal field:",
                    id="wizard-mapping-hint",
                )
                yield Vertical(id="wizard-mapping-container")

            # --- Step 2: Basic Settings ---
            with Vertical(id="wizard-step-2", classes="wizard-step"):
                yield Static("Settings", classes="wizard-step-title")
                with Horizontal(classes="form-field"):
                    yield Label("Rules name:")
                    yield Input(
                        placeholder="e.g. UniCredit Checking",
                        id="wizard-rules-name",
                    )
                with Horizontal(classes="form-field"):
                    yield Label("Bank account:")
                    yield AutocompleteInput(
                        placeholder="e.g. assets:bank:checking",
                        id="wizard-account1",
                    )
                with Horizontal(classes="form-field"):
                    yield Label("Currency:")
                    yield Input(
                        value=load_default_commodity(),
                        id="wizard-currency",
                    )
                with Horizontal(classes="form-field"):
                    yield Label("Date format:")
                    yield Input(
                        id="wizard-date-format",
                    )

            # --- Step 3: Conditional Rules ---
            with VerticalScroll(id="wizard-step-3", classes="wizard-step"):
                yield Static("Categorization Rules", classes="wizard-step-title")
                yield Static(
                    "When description matches... assign to account:",
                    id="wizard-conditional-hint",
                )
                yield Vertical(id="wizard-conditional-container")
                with Horizontal(id="wizard-conditional-buttons"):
                    yield Button("\\[+] Add rule", id="btn-wizard-add-rule")
                    yield Button("\\[-] Remove last", id="btn-wizard-remove-rule")
                yield Static(
                    "Optional. Unmatched transactions use expenses:unknown / income:unknown.",
                    id="wizard-conditional-note",
                )

            # --- Step 4: Raw Editor ---
            with Vertical(id="wizard-step-4", classes="wizard-step"):
                yield Static("Review & Save", classes="wizard-step-title")
                yield TextArea(id="wizard-raw-editor")

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
            self.accounts = load_accounts(self.journal_file)
        except HledgerError:
            self.accounts = []

        account1_input = self.query_one("#wizard-account1", AutocompleteInput)
        account1_input.suggester = SuggestFromList(self.accounts, case_sensitive=False)

        # If editing existing rules, populate from them
        if self.existing_rules:
            await self._init_from_existing()
        else:
            await self._init_auto_detect()

        self._show_step(0)

    async def _init_auto_detect(self) -> None:
        """Auto-detect CSV properties and populate initial values."""
        self._separator = detect_separator(self.csv_path)
        self._has_header, self._column_names = detect_header_row(
            self.csv_path, self._separator
        )
        skip = 1 if self._has_header else 0
        self._sample_rows = read_csv_preview(
            self.csv_path, self._separator, skip=skip, max_rows=10
        )
        self._field_mapping = auto_detect_field_mapping(
            self._column_names, self._sample_rows
        )

        # Detect date format from samples
        date_col = None
        for idx, field in enumerate(self._field_mapping):
            if field == "date":
                date_col = idx
                break
        if date_col is not None:
            date_samples = [
                row[date_col]
                for row in self._sample_rows
                if date_col < len(row)
            ]
            self._date_format = detect_date_format(date_samples)

        # Set UI values
        self._set_separator_select(self._separator)
        self.query_one("#wizard-header", Select).value = (
            "yes" if self._has_header else "no"
        )
        self.query_one("#wizard-date-format", Input).value = self._date_format
        self._populate_csv_preview()
        await self._populate_mapping()

    async def _init_from_existing(self) -> None:
        """Populate wizard from an existing rules file."""
        r = self.existing_rules
        assert r is not None

        self._separator = r.separator
        skip = r.skip
        self._has_header = skip > 0
        _, self._column_names = detect_header_row(self.csv_path, self._separator)
        if not self._has_header:
            # Generate generic column names matching field count
            count = max(len(r.field_mapping), len(self._column_names))
            self._column_names = [f"Col {i + 1}" for i in range(count)]
        self._sample_rows = read_csv_preview(
            self.csv_path, self._separator, skip=skip, max_rows=10
        )
        self._field_mapping = r.field_mapping
        # Pad if columns don't match
        while len(self._field_mapping) < len(self._column_names):
            self._field_mapping.append("")
        self._date_format = r.date_format

        self._set_separator_select(self._separator)
        self.query_one("#wizard-header", Select).value = (
            "yes" if self._has_header else "no"
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
        for _, val in _SEPARATOR_OPTIONS:
            if val == sep:
                select.value = val
                return
        select.value = ","

    def _populate_csv_preview(self) -> None:
        """Fill the CSV preview DataTable."""
        table = self.query_one("#wizard-csv-preview", DataTable)
        table.clear(columns=True)
        table.cursor_type = "none"

        if not self._column_names and not self._sample_rows:
            return

        for col_name in self._column_names:
            table.add_column(col_name, width=max(len(col_name) + 2, 12))

        for row in self._sample_rows[:10]:
            # Pad row if shorter than columns
            padded = row + [""] * (len(self._column_names) - len(row))
            table.add_row(*padded[: len(self._column_names)])

    async def _populate_mapping(self) -> None:
        """Build the column mapping widgets."""
        container = self.query_one("#wizard-mapping-container", Vertical)
        await container.remove_children()

        for i, col_name in enumerate(self._column_names):
            sample_val = ""
            if self._sample_rows and i < len(self._sample_rows[0]):
                sample_val = self._sample_rows[0][i]

            initial = self._field_mapping[i] if i < len(self._field_mapping) else ""

            row = Horizontal(classes="mapping-row", id=f"mapping-row-{i}")
            label = Label(f'"{col_name}"', classes="mapping-label")
            select = Select(
                options=_FIELD_OPTIONS,
                value=initial,
                id=f"mapping-select-{i}",
                classes="mapping-select",
            )
            sample = Static(f"  {sample_val}", classes="mapping-sample")
            row.compose_add_child(label)
            row.compose_add_child(select)
            row.compose_add_child(sample)
            container.mount(row)

    def _add_conditional_rule(
        self, pattern: str = "", account2: str = ""
    ) -> None:
        """Add a conditional rule row to step 3."""
        container = self.query_one("#wizard-conditional-container", Vertical)
        idx = self.conditional_rule_count

        row = Horizontal(
            classes="conditional-rule-row", id=f"cond-rule-{idx}"
        )
        pattern_input = Input(
            value=pattern,
            placeholder="pattern (e.g. grocery|food)",
            id=f"cond-pattern-{idx}",
            classes="cond-pattern",
        )
        acct_input = AutocompleteInput(
            value=account2,
            placeholder="account (e.g. expenses:groceries)",
            id=f"cond-account-{idx}",
            classes="cond-account",
        )
        acct_input.suggester = SuggestFromList(self.accounts, case_sensitive=False)

        container.mount(row)
        row.mount(pattern_input)
        row.mount(acct_input)
        self.conditional_rule_count += 1

    def _remove_last_conditional_rule(self) -> None:
        """Remove the last conditional rule row."""
        container = self.query_one("#wizard-conditional-container", Vertical)
        children = list(container.children)
        if children:
            children[-1].remove()
            self.conditional_rule_count -= 1
        else:
            self.notify("No rules to remove", severity="warning", timeout=3)

    # ------------------------------------------------------------------
    # Step navigation
    # ------------------------------------------------------------------

    def _show_step(self, step: int) -> None:
        """Show only the container for the given step."""
        self.current_step = step
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
        for i in range(len(self._column_names)):
            try:
                sel = self.query_one(f"#mapping-select-{i}", Select)
                val = sel.value
                field_mapping.append(val if val != Select.BLANK else "")
            except Exception:
                field_mapping.append("")

        # Collect conditional rules
        cond_rules: list[tuple[str, str]] = []
        for i in range(self.conditional_rule_count):
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
        if self.current_step == 1:
            return self._validate_mapping()
        if self.current_step == 2:
            return self._validate_settings()
        return True

    def _validate_mapping(self) -> bool:
        """Validate that at least date and amount (or amount-in) are mapped."""
        has_date = False
        has_amount = False
        has_amount_in = False

        for i in range(len(self._column_names)):
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
                self.dismiss(None)
            case "btn-wizard-back":
                if self.current_step > 0:
                    self._show_step(self.current_step - 1)
            case "btn-wizard-next":
                if self._validate_current_step():
                    self._show_step(self.current_step + 1)
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
        self._separator = sep
        self._has_header, self._column_names = detect_header_row(
            self.csv_path, self._separator
        )
        skip = 1 if self._has_header else 0
        self._sample_rows = read_csv_preview(
            self.csv_path, self._separator, skip=skip, max_rows=10
        )
        self._field_mapping = auto_detect_field_mapping(
            self._column_names, self._sample_rows
        )
        self.query_one("#wizard-header", Select).value = (
            "yes" if self._has_header else "no"
        )
        self._populate_csv_preview()
        await self._populate_mapping()

    @on(Select.Changed, "#wizard-header")
    async def _on_header_changed(self, event: Select.Changed) -> None:
        """Reload preview when header setting changes."""
        self._has_header = event.value == "yes"
        skip = 1 if self._has_header else 0
        if not self._has_header:
            # Re-detect without header
            self._column_names = [f"Col {i + 1}" for i in range(
                len(self._column_names) if self._column_names else 1
            )]
        else:
            _, self._column_names = detect_header_row(
                self.csv_path, self._separator
            )
        self._sample_rows = read_csv_preview(
            self.csv_path, self._separator, skip=skip, max_rows=10
        )
        self._field_mapping = auto_detect_field_mapping(
            self._column_names, self._sample_rows
        )
        self._populate_csv_preview()
        await self._populate_mapping()

    def _do_save(self) -> None:
        """Save the rules file and dismiss with paths."""
        editor = self.query_one("#wizard-raw-editor", TextArea)
        content = editor.text

        # Validate with hledger dry-run
        error = validate_rules_content(self.csv_path, content)
        if error:
            self.notify(
                f"Rules validation failed: {error}",
                severity="error",
                timeout=8,
            )
            return

        name = self.query_one("#wizard-rules-name", Input).value.strip() or "Unnamed"
        rules_dir = get_rules_dir(self.journal_file)
        rules_path = save_rules_file(rules_dir, name, content)

        self.dismiss((self.csv_path, rules_path))

    def action_cancel(self) -> None:
        """Cancel the wizard."""
        self.dismiss(None)


