#!/usr/bin/env bash
# ── SolarGuard daily cron job ──────────────────────────────────
# Run this every morning at 8 AM to scan all systems and send alerts.
#
# Install the cron job (Linux/Mac) with:
#   crontab -e
# then add:
#   0 8 * * * cd /home/user/solarguard && ./run_daily.sh >> logs/cron.log 2>&1
#
# Or, on Windows, use Task Scheduler to call this script.
# ───────────────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs

echo "[$(date)] Starting SolarGuard daily check..."

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

python monitor.py

echo "[$(date)] Daily check complete."
