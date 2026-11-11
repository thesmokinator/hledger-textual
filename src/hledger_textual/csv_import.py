"""CSV import backend: auto-detection, rules file management, and import execution.

The core strategy is to delegate CSV parsing to hledger via rules files,
while this module handles:

- Auto-detecting CSV separators, date formats, headers, and field mappings.
- Parsing and generating hledger rules files.
- Running ``hledger print`` for preview and using ``journal.append_transaction``
  for the actual import (respecting the GLOB/FLAT/FALLBACK routing).
- Duplicate detection against the existing journal.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from hledger_textual.config import load_rules_dir
from hledger_textual.hledger import HledgerError, _parse_transaction
from hledger_textual.models import CsvRulesFile, Transaction


class CsvImportError(Exception):
    """Raised when a CSV import operation fails."""


# ---------------------------------------------------------------------------
# Rules directory management
# ---------------------------------------------------------------------------


def get_rules_dir(journal_file: Path) -> Path:
    """Return the rules directory, creating it if necessary.

    Uses the configured ``[import] rules_dir`` from config.toml, or falls
    back to ``{journal_dir}/rules/``.

    Args:
        journal_file: Path to the main journal file (used for default dir).

    Returns:
        Path to the rules directory.
    """
    configured = load_rules_dir()
    if configured is not None:
        rules_dir = configured
    else:
        rules_dir = journal_file.parent / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    return rules_dir


def find_companion_rules(csv_path: Path) -> Path | None:
    """Return the companion rules file for *csv_path* if it exists.

    Follows hledger's convention: the rules file for ``bank.csv`` is
    ``bank.csv.rules`` in the same directory.  Returns ``None`` when no
    such file is found.

    Args:
        csv_path: Path to the CSV file being imported.

    Returns:
        Path to the companion rules file, or ``None``.
    """
    companion = csv_path.parent / (csv_path.name + ".rules")
    return companion if companion.is_file() else None


def list_rules_files(rules_dir: Path) -> list[CsvRulesFile]:
    """Scan ``*.rules`` files in a directory and parse their metadata.

    Args:
        rules_dir: Directory to scan.

    Returns:
        List of :class:`CsvRulesFile` instances sorted by name.
    """
    if not rules_dir.is_dir():
        return []
    results: list[CsvRulesFile] = []
    for p in sorted(rules_dir.glob("*.rules")):
        try:
            results.append(parse_rules_file(p))
        except Exception:
            continue
    return results


# ---------------------------------------------------------------------------
# CSV auto-detection
# ---------------------------------------------------------------------------


def detect_separator(csv_path: Path) -> str:
    """Auto-detect the CSV separator using :class:`csv.Sniffer`.

    Reads the first 5 lines and attempts to infer the delimiter.
    Falls back to ``','`` on failure.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        A single-character separator string.
    """
    try:
        with open(csv_path, encoding="utf-8") as f:
            sample = "".join(f.readline() for _ in range(5))
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except Exception:
        return ","


def detect_date_format(date_samples: list[str]) -> str:
    """Try common date formats against all samples.

    Args:
        date_samples: A list of date strings extracted from the CSV.

    Returns:
        The first ``strftime`` format that parses all samples, or
        ``'%Y-%m-%d'`` as a default.
    """
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        if all(_try_parse_date(s.strip(), fmt) for s in date_samples if s.strip()):
            return fmt
    return "%Y-%m-%d"


def _try_parse_date(s: str, fmt: str) -> bool:
    """Return True if *s* parses successfully with *fmt*."""
    try:
        datetime.strptime(s, fmt)
        return True
    except ValueError:
        return False


def detect_header_row(
    csv_path: Path, separator: str
) -> tuple[bool, list[str]]:
    """Heuristic: determine whether the first row is a header.

    If no cell in row 0 looks like a date or number, it is treated as a
    header.

    Args:
        csv_path: Path to the CSV file.
        separator: The CSV separator character.

    Returns:
        ``(has_header, column_names_or_indices)`` where column names come
        from the header row when detected, otherwise generic ``"Col 1"``
        labels.
    """
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=separator)
        first_row = next(reader, None)
    if first_row is None:
        return False, []

    # If any cell in the first row looks like a date or a number, assume no header
    date_re = re.compile(r"^\d{1,4}[-/\.]\d{1,2}[-/\.]\d{1,4}$")
    number_re = re.compile(r"^-?[\d,.]+$")
    for cell in first_row:
        cell = cell.strip()
        if date_re.match(cell) or (number_re.match(cell) and len(cell) > 1):
            # Likely data, not a header
            names = [f"Col {i + 1}" for i in range(len(first_row))]
            return False, names

    return True, [c.strip() for c in first_row]


_DATE_RE = re.compile(r"\d{1,4}[-/\.]\d{1,2}[-/\.]\d{1,4}")
_NUMBER_RE = re.compile(r"^-?[\d]+[,.]?\d*$")


def auto_detect_field_mapping(
    column_names: list[str], sample_rows: list[list[str]]
) -> list[str]:
    """Heuristic pre-selection of hledger field names for each CSV column.

    Uses both column names (if a header exists) and sample values.

    Args:
        column_names: Header labels or generic ``"Col N"`` names.
        sample_rows: A few rows of actual CSV data for value inspection.

    Returns:
        A list of hledger field names or ``""`` (skip) for each column.
    """
    mapping: list[str] = [""] * len(column_names)
    assigned: set[str] = set()

    # Pass 1: match by column name keywords
    name_hints: dict[str, list[str]] = {
        "date": ["date", "datum", "data", "valuta", "booking"],
        "description": [
            "description", "desc", "descrizione", "memo", "narrative",
            "payee", "beneficiary", "details", "reference",
        ],
        "amount": [
            "amount", "importo", "betrag", "sum", "value",
        ],
        "amount-in": ["credit", "income", "in", "deposit"],
        "amount-out": ["debit", "expense", "out", "withdrawal"],
    }

    for i, col in enumerate(column_names):
        col_lower = col.lower().strip()
        for field_name, keywords in name_hints.items():
            if field_name in assigned:
                continue
            if any(kw in col_lower for kw in keywords):
                mapping[i] = field_name
                assigned.add(field_name)
                break

    # Pass 2: use sample values for unassigned columns
    for i in range(len(column_names)):
        if mapping[i]:
            continue
        samples = [row[i].strip() for row in sample_rows if i < len(row)]
        if not samples:
            continue

        # Date-like?
        if "date" not in assigned and all(_DATE_RE.match(s) for s in samples if s):
            mapping[i] = "date"
            assigned.add("date")
            continue

        # Number-like?
        if "amount" not in assigned and all(
            _NUMBER_RE.match(s.replace(" ", "")) for s in samples if s
        ):
            mapping[i] = "amount"
            assigned.add("amount")
            continue

        # Long text → description
        if "description" not in assigned:
            avg_len = sum(len(s) for s in samples) / max(len(samples), 1)
            if avg_len > 10:
                mapping[i] = "description"
                assigned.add("description")

    return mapping


def validate_field_mapping(field_mapping: list[str]) -> list[str]:
    """Check a column-to-field mapping for missing or duplicated fields.

    Required fields are ``date``, ``description`` and an amount field
    (``amount``, or the ``amount-in``/``amount-out`` pair).  Every mapped
    field may appear at most once: hledger would silently use only one of
    two columns mapped to the same field.

    Args:
        field_mapping: One hledger field name (or ``""`` for skip) per CSV
            column, in column order.

    Returns:
        A list of human-readable error messages; empty when valid.
    """
    errors: list[str] = []
    seen: dict[str, int] = {}
    for idx, field_name in enumerate(field_mapping):
        if not field_name:
            continue
        if field_name in seen:
            errors.append(
                f"Field '{field_name}' is mapped twice "
                f"(columns {seen[field_name] + 1} and {idx + 1})"
            )
        else:
            seen[field_name] = idx

    if "date" not in seen:
        errors.append("Please map at least one column to 'date'")
    if "description" not in seen:
        errors.append("Please map at least one column to 'description'")
    if not ({"amount", "amount-in", "amount-out"} & seen.keys()):
        errors.append(
            "Please map at least one column to 'amount' "
            "or 'amount-in'/'amount-out'"
        )
    return errors


def read_csv_preview(
    csv_path: Path, separator: str, skip: int = 0, max_rows: int = 10
) -> list[list[str]]:
    """Read the first *max_rows* data rows from a CSV file.

    Args:
        csv_path: Path to the CSV file.
        separator: The CSV separator character.
        skip: Number of header/skip rows to ignore.
        max_rows: Maximum number of data rows to return.

    Returns:
        A list of rows, each a list of cell strings.
    """
    rows: list[list[str]] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=separator)
        for _ in range(skip):
            next(reader, None)
        for row in reader:
            rows.append(row)
            if len(rows) >= max_rows:
                break
    return rows


# ---------------------------------------------------------------------------
# Rules file parsing & generation
# ---------------------------------------------------------------------------


def parse_rules_file(rules_path: Path) -> CsvRulesFile:
    """Parse an hledger rules file into a :class:`CsvRulesFile`.

    Extracts ``skip``, ``separator``, ``date-format``, ``fields``,
    ``currency``, ``account1``, and ``if``/``account2`` blocks.  The
    display name is read from a ``; name: Xxx`` comment on the first line
    (our convention).

    Args:
        rules_path: Path to the ``.rules`` file.

    Returns:
        A :class:`CsvRulesFile` populated with the parsed metadata.
    """
    content = rules_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    name = rules_path.stem
    separator = ","
    date_format = "%Y-%m-%d"
    skip = 0
    field_mapping: list[str] = []
    currency = ""
    account1 = ""
    conditional_rules: list[tuple[str, str]] = []

    # Extract display name from first-line comment
    if lines and lines[0].strip().startswith(";"):
        m = re.match(r"^;\s*name:\s*(.+)$", lines[0].strip())
        if m:
            name = m.group(1).strip()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line or line.startswith(";"):
            i += 1
            continue

        if line.startswith("skip"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                try:
                    skip = int(parts[1])
                except ValueError:
                    pass
            else:
                skip = 1
            i += 1
            continue

        if line.startswith("separator"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                sep = parts[1].strip().strip('"').strip("'")
                if sep == "\\t" or sep.lower() == "tab":
                    separator = "\t"
                else:
                    separator = sep
            i += 1
            continue

        if line.startswith("date-format"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                date_format = parts[1].strip()
            i += 1
            continue

        if line.startswith("fields"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                field_mapping = [f.strip() for f in parts[1].split(",")]
            i += 1
            continue

        if line.startswith("currency"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                currency = parts[1].strip()
            i += 1
            continue

        if line.startswith("account1"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                account1 = parts[1].strip()
            i += 1
            continue

        if line.startswith("if"):
            pattern = line[2:].strip()
            # Collect the account2 from subsequent indented lines
            acct2 = ""
            i += 1
            while i < len(lines) and lines[i].startswith((" ", "\t")):
                inner = lines[i].strip()
                if inner.startswith("account2"):
                    parts = inner.split(None, 1)
                    if len(parts) == 2:
                        acct2 = parts[1].strip()
                i += 1
            if pattern and acct2:
                conditional_rules.append((pattern, acct2))
            continue

        i += 1

    return CsvRulesFile(
        name=name,
        path=rules_path,
        account1=account1,
        separator=separator,
        date_format=date_format,
        skip=skip,
        field_mapping=field_mapping,
        currency=currency,
        conditional_rules=conditional_rules,
    )


def generate_rules_content(
    name: str,
    separator: str,
    date_format: str,
    skip: int,
    field_mapping: list[str],
    currency: str,
    account1: str,
    conditional_rules: list[tuple[str, str]],
) -> str:
    """Generate the full text of a valid hledger rules file.

    The first line is ``; name: {name}`` as a metadata comment (our
    convention for display names).

    Args:
        name: Display name for the rules file.
        separator: CSV separator character.
        date_format: ``strftime`` format for the date column.
        skip: Number of header rows to skip.
        field_mapping: List of hledger field names (or empty to skip).
        currency: Default commodity symbol.
        account1: Default bank account.
        conditional_rules: List of ``(pattern, account2)`` pairs.

    Returns:
        The rules file content as a string.
    """
    lines: list[str] = []
    lines.append(f"; name: {name}")
    lines.append("")

    if skip:
        lines.append(f"skip {skip}")
        lines.append("")

    # Only write separator if not comma (hledger default)
    if separator and separator != ",":
        display_sep = "\\t" if separator == "\t" else separator
        lines.append(f"separator {display_sep}")
        lines.append("")

    if date_format:
        lines.append(f"date-format {date_format}")
        lines.append("")

    if field_mapping:
        fields_str = ", ".join(field_mapping)
        lines.append(f"fields {fields_str}")
        lines.append("")

    if currency:
        lines.append(f"currency {currency}")
        lines.append("")

    if account1:
        lines.append(f"account1 {account1}")
        lines.append("")

    for pattern, acct2 in conditional_rules:
        lines.append(f"if {pattern}")
        lines.append(f"  account2 {acct2}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug.

    Args:
        text: Display name to slugify.

    Returns:
        Lowercase, hyphen-separated string suitable for filenames.
    """
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "rules"


def save_rules_file(rules_dir: Path, name: str, content: str) -> Path:
    """Write a rules file to disk.

    The filename is derived from *name* via :func:`_slugify`.

    Args:
        rules_dir: Directory to save into.
        name: Display name (used to derive the filename).
        content: The full rules file content.

    Returns:
        The path to the saved file.
    """
    rules_dir.mkdir(parents=True, exist_ok=True)
    filename = _slugify(name) + ".rules"
    path = rules_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def delete_rules_file(rules_path: Path) -> None:
    """Delete a rules file from disk.

    Args:
        rules_path: Path to the ``.rules`` file to remove.
    """
    if rules_path.exists():
        rules_path.unlink()


# ---------------------------------------------------------------------------
# Import execution
# ---------------------------------------------------------------------------


def preview_import(csv_path: Path, rules_path: Path) -> list[Transaction]:
    """Run hledger to parse a CSV using a rules file and return transactions.

    Uses ``hledger print -f CSV --rules-file R -O json`` and parses the
    output with the existing :func:`_parse_transaction` helper.

    Args:
        csv_path: Path to the CSV file.
        rules_path: Path to the hledger rules file.

    Returns:
        A list of :class:`Transaction` objects.

    Raises:
        CsvImportError: If hledger fails.
    """
    cmd = [
        "hledger", "print",
        "-f", str(csv_path),
        "--rules-file", str(rules_path),
        "-O", "json",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
    except FileNotFoundError:
        raise CsvImportError(
            "hledger not found. Please install it: https://hledger.org/install.html"
        )
    except subprocess.CalledProcessError as exc:
        raise CsvImportError(f"hledger failed: {exc.stderr.strip()}")

    data = json.loads(result.stdout)
    return [_parse_transaction(t) for t in data]


def validate_rules_content(csv_path: Path, rules_content: str) -> str | None:
    """Validate rules content by doing a dry-run with hledger.

    Writes the rules to a temp file and runs ``hledger print`` to check
    for errors.

    Args:
        csv_path: Path to the CSV file.
        rules_content: The rules file text to validate.

    Returns:
        ``None`` if valid, otherwise an error message string.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".rules", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(rules_content)
        tmp_path = Path(tmp.name)
    try:
        preview_import(csv_path, tmp_path)
        return None
    except CsvImportError as exc:
        return str(exc)
    finally:
        tmp_path.unlink(missing_ok=True)


def check_duplicates(
    transactions: list[Transaction],
    journal_file: Path,
) -> tuple[list[Transaction], list[Transaction]]:
    """Separate new transactions from duplicates.

    Compares each transaction against the existing journal by
    ``(date, description, total_amount)``.

    Args:
        transactions: The candidate transactions from CSV preview.
        journal_file: Path to the main journal file.

    Returns:
        ``(new, duplicates)`` — two lists.
    """
    from hledger_textual.hledger import load_transactions

    try:
        existing = load_transactions(journal_file)
    except HledgerError:
        # If we can't load existing, assume all are new
        return transactions, []

    existing_keys: set[tuple[str, str, str]] = set()
    for txn in existing:
        key = (txn.date, txn.description.strip(), txn.total_amount.strip())
        existing_keys.add(key)

    new: list[Transaction] = []
    dupes: list[Transaction] = []
    for txn in transactions:
        key = (txn.date, txn.description.strip(), txn.total_amount.strip())
        if key in existing_keys:
            dupes.append(txn)
        else:
            new.append(txn)

    return new, dupes


def execute_import(
    csv_path: Path, rules_path: Path, journal_file: Path
) -> int:
    """Import transactions from a CSV into the journal.

    1. Calls :func:`preview_import` to parse the CSV via hledger.
    2. Filters out duplicates via :func:`check_duplicates`.
    3. Appends each new transaction via ``journal.append_transaction``
       (respecting GLOB/FLAT/FALLBACK routing).

    Args:
        csv_path: Path to the CSV file.
        rules_path: Path to the hledger rules file.
        journal_file: Path to the main journal file.

    Returns:
        The number of transactions imported.

    Raises:
        CsvImportError: If preview or import fails.
    """
    from hledger_textual.journal import JournalError, append_transaction

    transactions = preview_import(csv_path, rules_path)
    new_txns, _ = check_duplicates(transactions, journal_file)

    count = 0
    for txn in new_txns:
        try:
            append_transaction(journal_file, txn)
            count += 1
        except JournalError as exc:
            raise CsvImportError(
                f"Failed to import transaction '{txn.description}': {exc}"
            )
    return count
