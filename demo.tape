# hledger-textual demo
# Generates demo.gif for the README.
#
# Requires vhs: https://github.com/charmbracelet/vhs
# Record from the repository root with: vhs demo.tape

Output demo.gif

Set Shell zsh
Set Theme "Catppuccin Mocha"
Set FontSize 14
Set Width 1400
Set Height 800
Set Padding 10

# Isolated HOME with demo prices, so the investments table shows market values
# without touching the network or the recorder's real config.
Hide
Type "scripts/demo_env.sh"
Enter
Sleep 0.5s
Type "clear"
Enter
Show

Type@10ms "HOME=/tmp/hledger-textual-demo .venv/bin/hledger-textual -f examples/demo.journal"
Enter
Sleep 4s

# --- Accounts: drill into the checking account ---
Type "2"
Sleep 1.2s
Enter
Sleep 2.5s
Escape
Sleep 0.8s

# --- Transactions: search across the journal ---
Type "3"
Sleep 1.2s
Type "/"
Sleep 0.4s
Type "food"
Enter
Sleep 2s
Escape
Sleep 0.6s

# --- Budget: monthly table and multi-month overview ---
Type "4"
Sleep 1.5s
Type "o"
Sleep 2s
Escape
Sleep 0.8s

# --- Reports: income statement with chart ---
Type "6"
Sleep 1.5s
Type "c"
Sleep 2.5s
Escape
Sleep 0.8s

# --- Back to the Summary ---
Type "1"
Sleep 2s
Type "q"
Sleep 0.5s
