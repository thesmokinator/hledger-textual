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

### Navigating time

Every pane shares one period selection, so moving in time moves all of
them together. On startup the app opens on the current month, or — when the
current month has no transactions — on the month of the journal's latest
activity (with an explanatory notice).

Inside the app:

| Key | Effect |
| --- | --- |
| `g` | Open the "go to period" picker (Transactions, Summary, Reports, Budget) |
| `◄` / `►` | Step one month (Reports shifts its whole window) |
| `shift+◄` / `shift+►` | Step one year |
| `t` | Return to the current month |

The picker accepts hledger-style period expressions:

```
2024          whole year
2024-03       one month
2024-01..2024-06      month range
2024-03-05..2024-04-02        day range
this month · last month · next month · this/last/next year
ytd           year to date
all           the whole journal
march · mar 2024      month names
```

Selections outside the journal's data span are rejected with the actual
span shown. When the selected month is empty, Transactions offers a
"Jump to latest activity" hint (also available in Summary as `J`).

Caveats of the all-time view (`all`): the Summary cards and breakdown show
aggregates over the entire journal, so month-specific figures are not
visible there; the Transactions "Scheduled" split (future-dated
transactions at the end of the list) only appears on the current month.
For an at-a-glance view of a single period, prefer a month or year
selection.

At startup, the same scoping is available with the same flags as hledger:

```bash
hledger-textual -f all.journal -p 2024              # whole year
hledger-textual -f all.journal -p "last month"      # relative period
hledger-textual -f all.journal -p ytd               # year to date
hledger-textual -f all.journal -b 2024-01-01 -e 2024-06-30   # explicit range
```

`-p/--period` accepts any expression the period picker understands.
`-b/--begin` and `-e/--end` take precedence over `-p` bounds and behave
exactly like hledger (`--end` is exclusive). An invalid period aborts with
a clear message and a non-zero status instead of opening an empty UI.

The startup period is resolved in this order:

1. `-p` / `-b` / `-e` CLI arguments
2. the `default_period` key in `~/.config/hledger-textual/config.toml`
3. the current month — or, when the current month has no transactions, the
   month of the journal's latest activity (with an explanatory notice)

### Read-only mode

Open the journal for viewing only — every write path is disabled:

```bash
hledger-textual --read-only
```

When enabled:

- adding, editing, deleting, cloning, moving and status toggles are refused
  with a toast
- account note editing, CSV import, budget and recurring rules and the
  recurring auto-generation are disabled
- sync is disabled (a download could rewrite the journal)
- the footer carries a persistent `READ-ONLY` marker

Exports, search, saved filters, period navigation and drill-down keep
working. The mode can also be enabled with `read_only = true` in the config
file or the `HLEDGER_TEXTUAL_READ_ONLY=1` environment variable; the
`--read-only` flag takes precedence. See [Files written](#files-hledger-textual-writes)
for the complete list of files the app may write.

### Directive writes

The app only writes directives (include lines, account notes) from
explicit user actions, and previews them first. When you add the first
budget/recurring rule or save an account note, a confirmation dialog shows
the target file relative to the journal, the exact lines added or removed,
and the reason ("Budget rules live in budget.journal; hledger needs the
include directive to see them."). Cancel leaves every file byte-identical.

Checking **Don't ask again** persists `confirm_directive_writes = false`
in the config; setting the key back to `true` restores the prompt.

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
# default_period = "last month"
# read_only = true

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
