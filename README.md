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
- 💰 **Budgets** — monthly rules with actuals, remaining, percentage used, and a multi-month overview (3–36 months, per-year totals, CSV export)
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

### Multi-year budget overview

The Budget overview (`o` in the Budget pane) compares actuals against
your `~ monthly` rules across 3–36 months. A total column per calendar
year follows each December; rules that change over time (`~ monthly from
2025-06`) apply per month exactly as hledger computes them, so year
totals reflect each month's effective rule. Press `x` in the overview to
export the full table — months and year totals — to CSV or PDF.

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

## Files hledger-textual writes

Everything the app may write, when, and how to prevent it. The journal
stays a plain-text file you own — there is no database.

| File | Purpose | When written | Confirmation | Opt-out |
| --- | --- | --- | --- | --- |
| Your journal (transactions) | Add, edit, delete, clone, move, status toggles, CSV import | Only from explicit actions in the Transactions view | The edit/add forms show the full transaction before saving | `--read-only` |
| `budget.journal` (next to the journal) | Budget rules as `~ monthly` periodic transactions | Created on the first "add rule" action only — never on launch | Preview modal (file + diff) before the write | `--read-only`, or Cancel in the preview |
| `recurring.journal` (next to the journal) | Recurring transaction rules | Created on the first "add rule" action, or when the opt-in `auto_generate_recurring` generates pending transactions | Preview modal for the first rule; auto-generation writes only transactions it computed | `--read-only`, or Cancel in the preview |
| `include` lines in your journal | `include budget.journal` / `include recurring.journal` so hledger sees the rule files | Inserted together with the first rule of each kind | Preview modal (exact lines shown) | `--read-only`, or Cancel in the preview |
| `account` directives (notes) | Account notes/comments, written into the file that owns the account's postings | Only when you save a note | Preview modal (exact lines shown) | `--read-only`, or Cancel in the preview |
| CSV rules files (e.g. `bank.csv.rules` next to the CSV) | Mapping rules for CSV import | Saved from the import wizard | The full rules content is visible and validated (hledger dry-run) before saving | `--read-only` |
| Export directory (configurable) | CSV / PDF exports of table data | On an explicit export action, after choosing file and format | The export modal asks for directory and filename | Not applicable |
| Disk cache (system cache dir) | hledger output keyed by journal signature, including market prices — prices live there, never in your journal | Automatic, on first load of each query | None (transparent cache) | Delete the cache directory; it is rebuilt on demand |
| Config file (`~/.config/hledger-textual/config.toml`) | Theme, default commodity/period, tab order, saved filters, the "Don't ask again" choice | When you change a preference in the app (e.g. checking "Don't ask again") | None (it is your own preference change) | Edit the file manually |

The app never writes on launch, never keeps a database, and only touches
transactions from actions you perform in the UI. Every journal write is
atomic: the file is validated with `hledger check` and the original bytes
are restored on failure.

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

### Vendored test fixtures

`tests/fixtures/matrix/` contains four journals vendored **unmodified**
from the hledger repository (`hledgerorg/hledger`, `examples/`, pinned to
commit `61d999db5004253fdb0db188338122e0b545a9c2`) so the test suite runs
against the exact data of the [hledger UI test
matrix](https://hledger.org/uis.html). Those files are part of hledger and
are licensed **GPL-3.0**: they are redistributed here under their original
licence, are not covered by this project's MIT licence, and are excluded
from the published wheel/sdist. Their checksums are asserted by
`tests/test_matrix.py`; see `tests/fixtures/matrix/README.md` for the full
provenance note and the refresh procedure.

## License

[MIT](LICENSE.md)
