# hledger-textual

[![PyPI](https://img.shields.io/pypi/v/hledger-textual?label=PyPI&color=blue)](https://pypi.org/project/hledger-textual/)
[![GitHub Release](https://img.shields.io/github/v/release/thesmokinator/hledger-textual?label=GitHub&color=blue)](https://github.com/thesmokinator/hledger-textual/releases)
[![CI](https://github.com/thesmokinator/hledger-textual/actions/workflows/ci.yml/badge.svg)](https://github.com/thesmokinator/hledger-textual/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fthesmokinator%2Fhledger-textual%2Fmain%2Fcoverage.json&query=%24.totals.percent_covered_display&label=coverage&suffix=%25&color=green)](https://github.com/thesmokinator/hledger-textual/actions/workflows/ci.yml)

A full-featured terminal user interface for [hledger](https://hledger.org) plain-text accounting. Manage transactions, recurring rules, budgets, and investments — with multi-period reports, account drill-downs, and git sync — all from your terminal.

Built with [Textual](https://textual.textualize.io) and Python.

![hledger-textual demo](https://raw.githubusercontent.com/thesmokinator/hledger-textual/main/demo.gif)

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
Commodities without a price are shown in their original currency.

When nothing is resolved, the Accounts view shows each account's balances in
their original currencies (stacked within the cell), the Reports view's flat
multi-period mode marks multi-currency accounts with a `◆` prefix, and the
Summary overview shows a per-currency balance line under each card (marquee
scrolling when it overflows). The Reports view's stacked mode (`M`) always
expands each currency into its own row.

To pin a currency via config instead:

```toml
default_commodity = "€"
```

## Documentation

See the [Wiki](https://github.com/thesmokinator/hledger-textual/wiki) for the full documentation: feature overview, configuration, investment tracking, and per-tab reference.

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
