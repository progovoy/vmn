"""start_run(code=False) / VMN_EXP_CODE=none in a plain directory (no git)
with only the SDK importable: the run records metrics and no code, and every
code reader refuses it (plan 38 A10)."""
import os
import subprocess

from exp_helpers import _PY, _SRC_PATH

# As if only vmn-exp-sdk were installed: no git mode, no core vmn.
_SDK_ONLY = """
import sys
sys.modules["vmn_exp.gitmode"] = None
sys.modules["version_stamp"] = None
"""

_LOG_LOSS = """
from vmn_exp.sdk import start_run
with start_run({args}) as run:
    run.log_metric("loss", 0.25)
print(run.id)
"""

_READ_BACK = """
from vmn_exp.sdk import list_runs
rows = list_runs("app")
print(sorted((r["verstr"], r.get("parent"), r["metrics"]["loss"]) for r in rows))
"""


def _run(code, cwd, env):
    base = {k: v for k, v in os.environ.items()
            if not k.startswith(("VMN_EXP", "VMN_EXPERIMENT", "VMN_APP", "VMN_SNAPSHOT",
                                 "VMN_RESUME", "VMN_WORKING"))}
    proc = subprocess.run(
        [_PY, "-c", _SDK_ONLY + code], cwd=cwd, capture_output=True, text=True,
        env={**base, "PYTHONPATH": _SRC_PATH, "VMN_SYSTEM_METRICS": "0", **env},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip().splitlines()[-1]


def _plain(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    return str(plain), {"VMN_EXPERIMENT_DIR": str(tmp_path / "store")}


def test_start_run_code_false_logs_metrics_readable_by_list_runs(tmp_path):
    plain, store = _plain(tmp_path)
    first = _run(_LOG_LOSS.format(args="'app', code=False"), plain, store)
    second = _run(_LOG_LOSS.format(args=""), plain,
                  {**store, "VMN_EXP_CODE": "none", "VMN_APP_NAME": "app",
                   "VMN_EXPERIMENT_ID": first})
    assert (first, second) == ("0.0.0-nocode", "0.0.0-nocode.r2")
    rows = _run(_READ_BACK, plain, store)
    assert rows == str([(first, None, 0.25), (second, first, 0.25)])


def test_rerun_and_diff_refuse_a_codeless_run_with_no_code_snapshot(tmp_path):
    plain, store = _plain(tmp_path)
    verstr = _run(_LOG_LOSS.format(args="'app', code=False"), plain, store)
    reasons = _run(
        "from vmn_exp.core.provenance import no_code_reason\n"
        "from vmn_exp.core.rerun import rerun_blocker\n"
        "from vmn_exp.sdk.create import snapshot_mode_storage\n"
        f"meta = snapshot_mode_storage().load_metadata('app', {verstr!r})\n"
        "print([meta['codeless'], 'base_commit' in meta, rerun_blocker(meta), no_code_reason(meta)])\n",
        plain, store)
    reason = "recorded with code=False; no code snapshot"
    assert reasons == str([True, False, reason, reason])
