#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-quick}"
case "$MODE" in quick|normal|deep) ;; *) echo "Invalid mode" >&2; exit 2;; esac
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/home-filesystem-inventory"
mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/scan.lock"
flock -n 9 || { echo "Another scan is running" >&2; exit 1; }
cd "$PROJECT_DIR"
exec >>"$STATE_DIR/scan.log" 2>&1
echo "=== $(date -Is) Starting $MODE scan ==="
python3 -m home_inventory scan --mode "$MODE"
