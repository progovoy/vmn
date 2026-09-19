#!/usr/bin/env bash
# Start the Muster proxy + web UI for vmn local CI.
#
# First run installs muster into a dedicated venv.  The proxy serves
# the UI at http://localhost:8000 — trigger runs from the Trigger page,
# or let the daily schedule fire them automatically.
#
# Usage:
#   ./ci/start.sh                  # start proxy + UI
#   ./ci/start.sh --run-now        # also trigger one run immediately
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MTD_ROOT="$REPO_ROOT/../multi_target_debugger"
VENV_DIR="$REPO_ROOT/.mtd/muster_venv"
PYTHON="${VENV_DIR}/bin/python"

# ---- bootstrap muster venv (idempotent) ----
if [ ! -f "$PYTHON" ]; then
    echo "Creating muster venv at $VENV_DIR ..."
    /opt/homebrew/bin/python3.12 -m venv "$VENV_DIR"
fi

echo "Installing muster from $MTD_ROOT ..."
"$VENV_DIR/bin/pip" install --quiet -e "$MTD_ROOT"

MUSTER="$VENV_DIR/bin/muster"

# ---- ensure .mtd dirs exist ----
mkdir -p "$REPO_ROOT/.mtd/cache"
mkdir -p "$REPO_ROOT/.mtd/runs"
mkdir -p "$REPO_ROOT/.mtd/schedules"

# ---- seed the daily schedule if it doesn't exist ----
SCHED_FILE="$REPO_ROOT/.mtd/schedules/s-vmn-daily.json"
if [ ! -f "$SCHED_FILE" ]; then
    echo "Creating daily schedule ..."
    cat > "$SCHED_FILE" << 'SCHED'
{
  "id": "s-vmn-daily",
  "name": "vmn nightly tests",
  "cron": "0 2 * * *",
  "pipeline_file": "ci/pipeline.py",
  "params": {},
  "enabled": true
}
SCHED
fi

TOKEN="${VMN_CI_TOKEN:-vmn-local-ci}"

echo ""
echo "Muster proxy starting at http://localhost:8000"
echo "  UI:       http://localhost:8000/?token=${TOKEN}"
echo "  Pipeline: ci/pipeline.py"
echo "  Schedule: daily at 02:00 (edit via UI or $SCHED_FILE)"
echo "  State:    .mtd/runs/"
echo "  Cache:    .mtd/cache/"
echo ""

cd "$REPO_ROOT"

if [[ "${1:-}" == "--run-now" ]]; then
    echo "Triggering immediate run ..."
    "$MUSTER" run ci/pipeline.py \
        --state-dir .mtd/runs \
        --cache-dir .mtd/cache &
    RUN_PID=$!
    echo "Run started (pid $RUN_PID), launching proxy ..."
fi

exec "$MUSTER" proxy --web-port 8000 --auth-token "$TOKEN"
