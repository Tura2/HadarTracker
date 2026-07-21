#!/usr/bin/env bash
# Cron/systemd wrapper: run one incremental check from the repo root.
set -euo pipefail

# Move to the repo root (this script lives in deploy/).
cd "$(dirname "$0")/.."

# Load environment variables from .env if present.
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

exec ./.venv/bin/python -m hadar_tracker.check
