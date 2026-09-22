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

# Other checkouts run their own `muster proxy`, which also defaults to :8000, so
# the port is not ours to assume. Fail fast and name the holder instead of
# rebuilding the UI first and dying on the last line, and allow an override.
WEB_PORT="${MTD_WEB_PORT:-8000}"
if lsof -nP -iTCP:"$WEB_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $WEB_PORT is already in use:" >&2
    # One block per listener, each ending in the command that frees the port —
    # the holder is usually another checkout's `muster proxy`, so say which one.
    for pid in $(lsof -nP -tiTCP:"$WEB_PORT" -sTCP:LISTEN); do
        cmd="$(ps -ww -p "$pid" -o args= 2>/dev/null | head -1)" || cmd=''
        cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')" || cwd=''
        echo "  pid $pid  in ${cwd:-<unknown dir>}" >&2
        [ -n "$cmd" ] && echo "    $cmd" >&2
        echo "    kill $pid" >&2
    done
    echo "  ...or leave it alone and use another port:" >&2
    echo "    MTD_WEB_PORT=$((WEB_PORT + 10)) $0" >&2
    exit 1
fi


# ---- always rebuild the web UI against the latest muster source ----
# muster is installed editable, so `muster serve` serves $MTD_ROOT/ui/dist.
# Rebuild it on every start so UI source changes always ship (no stale bundle);
# node_modules is installed only when missing since deps rarely change.
UI_DIR="$MTD_ROOT/ui"
if command -v npm >/dev/null 2>&1; then
    [ -d "$UI_DIR/node_modules" ] || (cd "$UI_DIR" && npm install)
    echo "Rebuilding muster web UI from $UI_DIR ..."
    (cd "$UI_DIR" && npm run build)
else
    echo "npm not found — skipping UI rebuild (serving existing ui/dist)." >&2
fi

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
echo "Muster serve starting at http://localhost:$WEB_PORT"
echo "  UI:       http://localhost:$WEB_PORT"
echo "  Pipeline: ci/pipeline.py"
echo "  Schedule: daily at 02:00 (edit via UI or $SCHED_FILE)"
echo "  State:    .mtd/runs/"
echo "  Cache:    .mtd/cache/"
echo ""

cd "$REPO_ROOT"
export MTD_PIPELINES_DIR="$REPO_ROOT"
export MTD_PIPELINE_STATE_DIR="$REPO_ROOT/.mtd/runs"

if [[ "${1:-}" == "--run-now" ]]; then
    echo "Triggering immediate run ..."
    "$MUSTER" run ci/pipeline.py \
        --state-dir .mtd/runs \
        --cache-dir .mtd/cache &
    RUN_PID=$!
    echo "Run started (pid $RUN_PID), launching server ..."
fi

exec "$MUSTER" serve --no-auth --web-port "$WEB_PORT"
