"""Shared state for the CSV import wizard steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hledger_textual.models import CsvRulesFile


@dataclass
class WizardState:
    """State shared by all import wizard steps, passed by reference.

    The parent screen owns the single instance; each step widget reads
    and updates it as the user moves through the wizard.
    """

    csv_path: Path
    journal_file: Path
    existing_rules: CsvRulesFile | None = None
    current_step: int = 0
    accounts: list[str] = field(default_factory=list)
    conditional_rule_count: int = 0

    # Detected/configured values (populated on mount)
    separator: str = ","
    has_header: bool = True
    column_names: list[str] = field(default_factory=list)
    sample_rows: list[list[str]] = field(default_factory=list)
    field_mapping: list[str] = field(default_factory=list)
    date_format: str = "%Y-%m-%d"
