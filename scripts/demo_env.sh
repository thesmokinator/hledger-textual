#!/usr/bin/env bash
# Prepare an isolated HOME for recording demo.tape.
#
# The demo journal holds ETFs, so the Summary tries to fetch market prices
# through pricehist when a ticker is configured.  Recording must be offline and
# deterministic, so this script writes a config with tickers and a price cache
# dated today: the app sees fresh prices and never hits the network.
set -euo pipefail

DEMO_HOME="${DEMO_HOME:-/tmp/hledger-textual-demo}"
CONFIG_DIR="$DEMO_HOME/.config/hledger-textual"
CACHE_DIR="$DEMO_HOME/.cache/hledger-textual"

rm -rf "$DEMO_HOME"
mkdir -p "$CONFIG_DIR" "$CACHE_DIR"

cat > "$CONFIG_DIR/config.toml" <<'EOF'
[prices]
XDWD = "XDWD.MI"
XEON = "XEON.MI"
XGDU = "XGDU.MI"
EOF

today="$(date +%F)"
cat > "$CACHE_DIR/prices.journal" <<EOF
P $today XDWD €120.00
P $today XEON €150.00
P $today XGDU €65.00
EOF

printf '%s\n' "$DEMO_HOME"
