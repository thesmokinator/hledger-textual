# hledger-textual

[![PyPI](https://img.shields.io/pypi/v/hledger-textual?label=PyPI&color=blue)](https://pypi.org/project/hledger-textual/)
[![GitHub Release](https://img.shields.io/github/v/release/thesmokinator/hledger-textual?label=GitHub&color=blue)](https://github.com/thesmokinator/hledger-textual/releases)
[![CI](https://github.com/thesmokinator/hledger-textual/actions/workflows/ci.yml/badge.svg)](https://github.com/thesmokinator/hledger-textual/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fthesmokinator%2Fhledger-textual%2Fmain%2Fcoverage.json&query=%24.totals.percent_covered_display&label=coverage&suffix=%25&color=green)](https://github.com/thesmokinator/hledger-textual/actions/workflows/ci.yml)

A full-featured terminal user interface for [hledger](https://hledger.org) plain-text accounting. Manage transactions, recurring rules, budgets, and investments — with multi-period reports, account drill-downs, and git sync — all from your terminal.

Built with [Textual](https://textual.textualize.io) and Python.

![hledger-textual demo](https://raw.githubusercontent.com/thesmokinator/hledger-textual/main/demo.gif)

## ✨ Feature highlights

- 📊 Multi-period reports — monthly, quarterly, yearly, and custom ranges, with charts
- 🔁 Recurring transaction rules with calendar view and one-shot generation
- 💰 Budgets with overview screen and per-category drill-down
- 📥 CSV import wizard with separator/header detection and rule editor
- 📈 Investment tracking with cost basis and market value conversion
- 🔄 Git sync and cloud sync support for the journal
- 🧩 Custom report builder with saved filters
- 🏦 Account hierarchy with directives (notes, metadata)
- 📄 PDF / CSV export of every view

## Why hledger-textual?

hledger-textual is the most advanced TUI in the hledger ecosystem, with feature parity for budgets, recurring transactions, investments, and reports. Everything lives in plain-text files you already own — the journal, a `budget.journal` for budgets, CSV rules for imports — so no database, no lock-in, and git-friendly versioning of your finances.

## Stack

- **Python 3.12+**
- **Textual** - TUI framework
- **hledger** - plain-text accounting (must be installed separately)
- **uv** - package manager (no `requirements.txt` needed, dependencies are in `pyproject.toml`)
- **pytest** - testing

## Requirements

- Python 3.12+
- [hledger](https://hledger.org/install.html) installed and available in `PATH`

## Installation

```bash
# With pipx
pipx install hledger-textual

# With uv
uv tool install hledger-textual
```

## Usage

```bash
hledger-textual -f path/to/your.journal
```

The journal file is resolved in this order:

1. `-f` / `--file` CLI argument
2. `LEDGER_FILE` environment variable
3. `~/.config/hledger-textual/config.toml` (`journal_file` key)
4. `~/.hledger.journal`

### Default currency

For multi-currency journals, the default currency is resolved in this order:

1. The first `commodity` directive declared in the journal (following
   `include` files), e.g. `commodity €1,000.00`.
2. The `default_commodity` key in `~/.config/hledger-textual/config.toml`.

When resolved, the Accounts and Summary views convert balances to that
currency using `hledger -X --infer-market-prices`, so `P` price directives in
the journal are honored (see `examples/multicurrency-prices.journal`).
Commodities without a price are shown in their original currency, and the
Summary's Income / Expenses / Liabilities breakdowns show `—` instead of a
percentage for them (a note names the excluded commodities). Percentages are
always computed on converted amounts, so rows in different currencies are
never compared one-to-one.

When nothing is resolved, the Accounts view shows each account's balances in
their original currencies (stacked within the cell), the Reports view's flat
multi-period mode marks multi-currency accounts with a `◆` prefix, and the
Summary overview shows a per-currency balance line under each card (marquee
scrolling when it overflows). The Reports view's stacked mode (`M`) always
expands each currency into its own row. Summary breakdown percentages stay
hidden (`—`) for journals that mix currencies in that case, since there is no
common denominator; single-currency journals are unaffected.

To pin a currency via config instead:

```toml
default_commodity = "€"
```

## Configuration

Full reference: the [Wiki](https://github.com/thesmokinator/hledger-textual/wiki) documents every option. A minimal `~/.config/hledger-textual/config.toml`:

```toml
journal_file = "~/finance/all.journal"
default_commodity = "€"
theme = "nord"

# Reorder the tabs (any subset; missing tabs keep their default order)
tab_order = ["summary", "accounts", "transactions", "budget", "recurring", "reports"]
```

## Documentation

See the [Wiki](https://github.com/thesmokinator/hledger-textual/wiki) for the full documentation: feature overview, configuration, investment tracking, and per-tab reference.

## Roadmap

Planned work is tracked as [enhancement issues](https://github.com/thesmokinator/hledger-textual/labels/enhancement) — vote, comment, or pick one up.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, test suite, and pull-request flow.

## Development

```bash
git clone https://github.com/thesmokinator/hledger-textual.git
cd hledger-textual
uv sync
```

### Testing

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run with coverage report
uv run pytest --cov=hledger_textual --cov-report=term-missing
```
