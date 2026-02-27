# hledger-textual Documentation

A terminal user interface for [hledger](https://hledger.org) plain-text accounting.
Browse transactions, track budgets, monitor investments, and manage your journal — all from the terminal.

![hledger-textual summary](https://raw.githubusercontent.com/thesmokinator/hledger-textual/main/screenshots/001.png)

## Table of Contents

- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Navigation](#navigation)
- [Tab 1 — Summary](#tab-1--summary)
- [Tab 2 — Transactions](#tab-2--transactions)
- [Tab 3 — Budget](#tab-3--budget)
- [Tab 4 — Reports](#tab-4--reports)
- [Tab 5 — Accounts](#tab-5--accounts)
- [Tab 6 — Info](#tab-6--info)
- [Investment Tracking](#investment-tracking)
- [Demo Journal](#demo-journal)

---

## Getting Started

### Prerequisites

- Python 3.12+
- [hledger](https://hledger.org/install.html) installed and available in `PATH`
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- (Optional) [pricehist](https://pypi.org/project/pricehist/) for live market prices

### Installation

```bash
git clone https://github.com/thesmokinator/hledger-textual.git
cd hledger-textual
uv sync
```

### Running

```bash
uv run hledger-textual -f path/to/your.journal
```

The journal file is resolved in this order:

1. `-f` / `--file` CLI argument
2. `LEDGER_FILE` environment variable
3. `journal_file` key in `~/.config/hledger-textual/config.toml`
4. `~/.hledger.journal`

---

## Configuration

The configuration file lives at `~/.config/hledger-textual/config.toml`.

```toml
journal_file = "/path/to/your.journal"
theme = "textual-dark"

[prices]
XDWD = "XDWD.MI"
XEON = "XEON.MI"
XGDU = "XGDU.MI"
```

| Key | Description |
|-----|-------------|
| `journal_file` | Path to the hledger journal file |
| `theme` | Textual theme name (can also be changed via the theme picker, see [Tab 6 — Info](#tab-6--info)) |
| `[prices]` | Mapping of journal commodity names to Yahoo Finance tickers |

The `[prices]` section enables live market price fetching for investment tracking (see [Investment Tracking](#investment-tracking)).

---

## Navigation

Switch between tabs using number keys. Arrow keys never change tabs.

| Key | Action |
|-----|--------|
| `1` | Summary |
| `2` | Transactions |
| `3` | Budget |
| `4` | Reports |
| `5` | Accounts |
| `6` | Info |
| `t` | Open theme picker |
| `q` | Quit |

Each tab shows context-specific key hints in the footer bar.

---

## Tab 1 — Summary

A financial dashboard for the current calendar month.

### Cards

Three cards at the top show **Income**, **Expenses**, and **Net** for the current month.

Net represents disposable income: `income - expenses - investments`. When investments are present, a note below the Net card shows the invested amount (e.g. *incl. €1,069.00 invested*).

- Green Net = you saved money this month
- Red Net = you spent more than you earned (including investments)

### Investments

A portfolio table showing all non-EUR holdings:

| Column | Description |
|--------|-------------|
| Asset | Commodity name (e.g. XDWD) |
| Quantity | Number of units held |
| Balance | Purchase cost (book value) |
| Market Value | Current value in EUR via pricehist |

Market values are color-coded: green for gains, red for losses relative to book value.

### This Month's Expenses

A breakdown of expenses by account, sorted by amount descending. Each row includes a visual progress bar and percentage of total spending.

| Key | Action |
|-----|--------|
| `r` | Refresh all data |

---

## Tab 2 — Transactions

Browse, search, create, edit, and delete journal transactions.

### Month Navigation

Use left/right arrow keys to browse one month at a time. The current month label is shown in the header.

### Search

Press `/` to open the search bar. It accepts **hledger query syntax** with short aliases:

| Alias | Expands to | Example |
|-------|-----------|---------|
| `d:` | `desc:` | `d:grocery` — match description |
| `ac:` | `acct:` | `ac:food` — match account name |
| `am:` | `amt:` | `am:>100` — match by amount |

Full hledger prefixes also work directly: `desc:grocery`, `acct:food`, `amt:>100`, `tag:project`.

Press `Escape` to clear the search and return to month navigation.

### CRUD Operations

| Key | Action |
|-----|--------|
| `a` | Add new transaction |
| `e` / `Enter` | Edit selected transaction |
| `d` | Delete with confirmation |
| `Left` / `Right` | Previous / next month |
| `/` | Search (hledger query syntax) |
| `r` | Refresh |
| `j` / `k` | Navigate rows |

The transaction form supports:

- Date picker with validation
- Status selection (unmarked, pending `!`, cleared `*`)
- Description with autocomplete from existing descriptions
- Dynamic posting rows with account autocomplete and amount input

---

## Tab 3 — Budget

Define monthly budget rules and compare actual spending against targets.

### Budget Rules

Budget rules are stored in a separate file (automatically managed alongside your journal). Each rule maps an account to a monthly budget amount using hledger's periodic transaction syntax:

```
~ monthly
    expenses:food:groceries    €400.00
    expenses:housing:rent      €800.00
    assets:budget
```

### Budget Table

| Column | Description |
|--------|-------------|
| Account | The budgeted account |
| Budget | Monthly budget amount |
| Actual | Actual spending this month |
| Remaining | Budget minus actual |
| % Used | Usage percentage |

Color coding: green (< 75%), yellow (75–100%), red (> 100% — over budget).

| Key | Action |
|-----|--------|
| `a` | Add new budget rule |
| `e` / `Enter` | Edit selected rule |
| `d` | Delete with confirmation |
| `Left` / `Right` | Previous / next month |
| `/` | Filter by account name |
| `r` | Refresh |
| `j` / `k` | Navigate rows |

---

## Tab 4 — Reports

Multi-period financial reports powered by hledger.

| Key | Action |
|-----|--------|
| `r` | Reload |
| `q` | Quit |

---

## Tab 5 — Accounts

A list of all accounts with their current balances. Select an account and press `Enter` to drill down into its transactions.

### Account Detail Screen

Opens a full-screen view filtered to a single account, showing its transaction history. Supports the same edit, delete, and search operations as the main Transactions tab. Press `Escape` to go back.

| Key | Action |
|-----|--------|
| `Enter` | Drill into account transactions |
| `/` | Filter by account name |
| `r` | Refresh |
| `Escape` | Dismiss filter |
| `j` / `k` | Navigate rows |

---

## Tab 6 — Info

Displays journal statistics, configuration, and application metadata in a two-column layout.

### Left Column

**Journal** — Path, file size, transaction count, account count, and commodities list.

**Configuration** — Config file path and current theme name.

### Right Column

**About** — Application name, version, author, license, and repository URL.

**hledger** — hledger version and pricehist installation status.

### Theme Picker

Press `t` to open the theme picker dialog. Select a theme from the list and press `Enter` to apply it. The theme is persisted to `config.toml` automatically. Press `Escape` to cancel.

Available themes: textual-dark, textual-light, nord, dracula, gruvbox, catppuccin-mocha, catppuccin-latte, tokyo-night, monokai, flexoki, solarized-light, textual-ansi.

| Key | Action |
|-----|--------|
| `t` | Open theme picker |
| `q` | Quit |

---

## Investment Tracking

hledger-textual can track investment portfolios and fetch live market prices.

### Setup

1. Record investment purchases in your journal using hledger cost annotations:

   ```
   2026-01-15 * Buy XDWD
       assets:investments:XDWD    10 XDWD @@ €1,185.00
       assets:bank:checking      €-1,185.00
   ```

2. Install [pricehist](https://pypi.org/project/pricehist/) for live price fetching:

   ```bash
   pipx install pricehist
   ```

3. Map your commodity names to Yahoo Finance tickers in `config.toml`:

   ```toml
   [prices]
   XDWD = "XDWD.MI"
   XEON = "XEON.MI"
   ```

### How It Works

On each app launch, hledger-textual:

1. Loads investment positions and book values from your journal via hledger
2. Fetches today's market prices from Yahoo Finance via pricehist (cached daily in `~/.cache/hledger-textual/prices.journal`)
3. Displays the portfolio table with book value vs market value
4. Includes investment purchases in the Net calculation on the Summary tab

If pricehist is not installed or a ticker is not configured, the Market Value column shows "—" and a hint message is displayed.

---

## Demo Journal

A demo journal is included for testing and exploration:

```bash
uv run hledger-textual -f examples/demo.journal
```

It contains two months of realistic personal finance data (January–February 2026) covering all six tabs: income, expenses, bank transfers, investment purchases (XDWD, XEON, XGDU), and budget rules.
