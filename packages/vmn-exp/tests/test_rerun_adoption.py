"""`vmn-exp rerun` of a run whose script calls ``start_run()``: the script in the
restored workspace records into the rerun (plan 38 A12). Real git."""
import os

import pytest
from exp_helpers import _PY, _SRC_PATH, _bootstrap, _exec_script, _exp
from rerun_helpers import log, meta, rerun, run_names

from vmn_exp.core.streams import GUEST_WRITER_SUFFIX

TRAIN = (
    "from vmn_exp.sdk import start_run\n"
    "with start_run() as run:\n"
    "    run.log_metric('m', 5)\n"
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_DIR", "VMN_EXP_ADOPT", "VMN_EXP_ADOPT_RUN_ID",
                "VMN_EXP_ADOPT_PID"):
        monkeypatch.delenv(key, raising=False)
    # The child imports this tree's SDK, not an installed one.
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(
        p for p in (_SRC_PATH, os.environ.get("PYTHONPATH")) if p))


def _original(app_layout):
    _bootstrap(app_layout)
    _exec_script(app_layout, "train.py", TRAIN)
    assert _exp(app_layout.app_name, action="run", run_cmd=[_PY, "train.py"]) == 0
    (orig,) = run_names(app_layout)
    return orig


def _has_metric(app_layout, verstr):
    return any(e.get("values", {}).get("m") == 5 for e in log(app_layout, verstr))


def test_rerun_child_resolves_the_same_store_and_adopts(app_layout):
    orig = _original(app_layout)

    rc, new = rerun(app_layout, orig)

    assert rc == 0 and meta(app_layout, new)["rerun_of"] == orig
    assert _has_metric(app_layout, new)
    assert any(e.get("_writer", "").endswith(GUEST_WRITER_SUFFIX)
               for e in log(app_layout, new) if e.get("values"))


def test_rerun_with_no_adopt_keeps_wrapper_plus_inner(app_layout):
    orig = _original(app_layout)
    before = run_names(app_layout)

    assert _exp(app_layout.app_name, action="rerun", version=orig,
                extra_args=["--no-adopt"]) == 0

    new = run_names(app_layout) - before
    (outer,) = [v for v in new if meta(app_layout, v).get("rerun_of") == orig]
    (inner,) = new - {outer}
    assert meta(app_layout, inner)["parent"] == outer
    assert _has_metric(app_layout, inner) and not _has_metric(app_layout, outer)
