# hledger-textual

[![PyPI](https://img.shields.io/pypi/v/hledger-textual?label=PyPI&color=blue)](https://pypi.org/project/hledger-textual/)
[![GitHub Release](https://img.shields.io/github/v/release/thesmokinator/hledger-textual?label=GitHub&color=blue)](https://github.com/thesmokinator/hledger-textual/releases)
[![CI](https://github.com/thesmokinator/hledger-textual/actions/workflows/ci.yml/badge.svg)](https://github.com/thesmokinator/hledger-textual/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fthesmokinator%2Fhledger-textual%2Fmain%2Fcoverage.json&query=%24.totals.percent_covered_display&label=coverage&suffix=%25&color=green)](https://github.com/thesmokinator/hledger-textual/actions/workflows/ci.yml)

**Your finances, in the terminal — beautiful, fast, and entirely plain text.**

hledger-textual is a full-featured terminal UI for [hledger](https://hledger.org). Review accounts, add and edit transactions, track budgets, recurring rules and investments, and explore multi-period reports — all without leaving your keyboard or giving up ownership of your data.

Built with [Textual](https://textual.textualize.io) and Python.

![hledger-textual demo](https://raw.githubusercontent.com/thesmokinator/hledger-textual/main/demo.gif)

## Why hledger-textual?

- **No database, no lock-in.** Your journal stays a plain-text file you own, version, and sync with git.
- **Fast on real journals.** Parallel hledger queries, progressive rendering, and a persistent cache keep large journals responsive.
- **Everything in one place.** Summary, accounts, transactions, budgets, recurring rules, investments, CSV imports, and custom reports.
- **Keyboard first.** Quick navigation, search, drill-downs, and a command palette — the mouse is optional.
- **Yours to configure.** Themes, tab order, default currency, saved filters, and custom reports.

## Features

- 📊 **Reports** — monthly, quarterly and yearly income statements, balance sheets, cash flow, charts, and saved custom reports
- 🏦 **Accounts** — hierarchical or flat balances, search, and full transaction drill-down
- ✍️ **Transactions** — add, edit, delete, clone, move, filter, and export, with recurring rules and a calendar
- 💰 **Budgets** — monthly rules with actuals, remaining, percentage used, and a multi-month overview
- 📈 **Investments** — positions, cost basis, market value, and unrealised P/L for ETFs and securities
- 📥 **Imports** — CSV wizard with separator/header detection and reusable rules
- 🔄 **Sync** — git or rclone sync for your journal
- 📄 **Exports** — PDF and CSV from every view

## Install

Requires Python 3.12+ and [hledger](https://hledger.org/install.html) available in `PATH`.

```bash
# With pipx
pipx install hledger-textual

# With uv
uv tool install hledger-textual
```

## Quick start

```bash
hledger-textual -f path/to/your.journal
```

Or try the bundled demo:

```bash
git clone https://github.com/thesmokinator/hledger-textual.git
cd hledger-textual
uv sync
uv run hledger-textual -f examples/demo.journal
```

The journal is resolved in this order:

1. `-f` / `--file` CLI argument
2. `LEDGER_FILE` environment variable
3. `~/.config/hledger-textual/config.toml` (`journal_file` key)
4. `~/.hledger.journal`

## Performance

Independent hledger queries run concurrently, the Summary paints its cards before loading the rest, and every tab keeps loading in the background. A persistent disk cache makes restarting on an unchanged journal effectively instant.

Indicative timings on an Apple M4 (10 cores), macOS, Python 3.12, Textual 8.2.8, and hledger 1.52, with synthetic journals from [`scripts/generate_synthetic_journal.py`](scripts/generate_synthetic_journal.py):

| | 10k txns | 50k txns | 100k txns |
|---|---:|---:|---:|
| First Summary figures | 0.7 s | 2.7 s | 5.2 s |
| Full Summary | 1.1 s | 4.2 s | 8.5 s |
| All tabs preloaded | 1.6 s | 6.8 s | 14.3 s |
| Restart with warm cache | 0.2 s | 0.2 s | 0.3 s |

Timings depend on hardware, disk, and journal shape. Reproduce them with:

```bash
uv run python scripts/benchmark_perf.py --transactions 100000
```

The cache lives under the platform cache directory (`~/Library/Caches/hledger-textual` on macOS, `$XDG_CACHE_HOME/hledger-textual` on Linux). Set `HLEDGER_TEXTUAL_NO_DISK_CACHE=1` to disable it or `HLEDGER_TEXTUAL_CACHE_DIR=/path` to move it.

## Configuration

A minimal `~/.config/hledger-textual/config.toml`:

```toml
journal_file = "~/finance/all.journal"
theme = "nord"

# Reorder the tabs (any subset; missing tabs keep their default order)
tab_order = ["summary", "accounts", "transactions", "budget", "recurring", "reports"]
```

The [`Wiki`](https://github.com/thesmokinator/hledger-textual/wiki) documents every option, including multi-currency journals, investment price tickers, sync, and custom reports.

## Documentation

Full reference in the [Wiki](https://github.com/thesmokinator/hledger-textual/wiki). Press `?` in the app for the keyboard shortcuts.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, test suite, and pull-request flow. Planned work is tracked as [enhancement issues](https://github.com/thesmokinator/hledger-textual/labels/enhancement) — vote, comment, or pick one up.

## License

[MIT](LICENSE.md)
