#!/usr/bin/env bash
# Start the Muster pipeline server + web UI for vmn local CI.
#
# First run installs muster into a dedicated venv.  The server runs in
# pipeline-only mode (no DAP proxy) with no auth required.
#
# Usage:
#   ./ci/start.sh                  # start server + UI
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
  "cache_dir": ".mtd/cache",
  "enabled": true
}
SCHED
fi

echo ""
echo "Muster serve starting at http://localhost:8000"
echo "  UI:       http://localhost:8000"
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
    echo "Run started (pid $RUN_PID), launching server ..."
fi

exec "$MUSTER" serve --no-auth --web-port 8000
