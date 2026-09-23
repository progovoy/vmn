"""Autolog records into the right run, exactly once, and imports nothing extra.

Regression tests for the review findings on ``version_stamp/exp/autolog.py``:

* four threaded trials, each under its own ``start_run()``, all recorded into
  whichever run opened last (the process-global ``_OPEN_RUNS[-1]``);
* sklearn's own worker threads (``IsolationForest(n_jobs=4)``, a threading
  joblib backend) bypassed the thread-local nested-fit guard and logged every
  sub-estimator;
* forked ``multiprocessing`` workers wrote into the parent's run;
* two fits in one run wrote the same artifact name, so the first entry's sha256
  no longer matched the file on disk;
* ``log_models`` defaulted to True and a second ``autolog()`` ignored new options;
* ``autolog()`` imported every installed framework.
"""
import hashlib
import multiprocessing
import os
import subprocess
import sys
import threading
import warnings

import pytest

sklearn = pytest.importorskip("sklearn")

from helpers import _bootstrap, _storage  # noqa: E402
from sklearn.ensemble import IsolationForest  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.model_selection import GridSearchCV  # noqa: E402

from version_stamp.exp import autolog, autolog_disable, start_run  # noqa: E402
from version_stamp.exp import run as run_module  # noqa: E402
from version_stamp.exp.reader import get_run  # noqa: E402

X = [[0.0], [1.0], [2.0], [3.0], [10.0], [11.0], [12.0], [13.0]]
Y = [0, 0, 0, 0, 1, 1, 1, 1]


@pytest.fixture(autouse=True)
def restore_frameworks():
    yield
    autolog_disable()
    assert run_module._OPEN_RUNS == []


@pytest.fixture(autouse=True)
def quiet_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _row(app_layout, verstr):
    return get_run(app_layout.app_name, verstr, storage=_storage(app_layout))


def _params_entries(row):
    return [e["params"] for e in row["log"] if e.get("type") == "params"]


def _estimators(row):
    params = _params_entries(row)
    return [p["sklearn_estimator"] for p in params if "sklearn_estimator" in p]


# --- the right run ---------------------------------------------------------


def test_threaded_trials_each_record_into_their_own_run(app_layout):
    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"])
    barrier = threading.Barrier(4)
    ids = {}

    def trial(i):
        with start_run(app_layout.app_name, note=f"trial {i}") as run:
            ids[i] = run.id
            barrier.wait(timeout=60)  # every run is open before anyone fits
            LogisticRegression(C=float(i + 1)).fit(X, Y)
            barrier.wait(timeout=60)

    threads = [threading.Thread(target=trial, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i, verstr in ids.items():
        row = _row(app_layout, verstr)
        assert _estimators(row) == ["LogisticRegression"], (i, row["log"])
        assert row["params"]["sklearn_C"] == float(i + 1)


def test_sklearn_worker_threads_do_not_record_sub_estimators(app_layout):
    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"])
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        IsolationForest(n_estimators=40, n_jobs=4, random_state=0).fit(X)

    row = _row(app_layout, verstr)
    assert _estimators(row) == ["IsolationForest"]
    assert row["params"]["sklearn_estimator"] == "IsolationForest"


def test_threading_backend_grid_search_records_only_the_outer_fit(app_layout):
    from joblib import parallel_backend

    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"])
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        with parallel_backend("threading", n_jobs=2):
            GridSearchCV(LogisticRegression(), {"C": [0.1, 1.0, 10.0]}, cv=2).fit(X, Y)

    row = _row(app_layout, verstr)
    assert _estimators(row) == ["GridSearchCV"]
    assert "sklearn_best_C" in row["params"]
    assert "sklearn_best_cv_score" in row["metrics"]


def _fit_in_child(_):
    LogisticRegression().fit(X, Y)
    return os.getpid()


def test_forked_workers_never_record_into_the_parent_run(app_layout):
    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"])
    ctx = multiprocessing.get_context("fork")
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        with ctx.Pool(2) as pool:
            pids = pool.map(_fit_in_child, range(4))

    assert os.getpid() not in pids
    row = _row(app_layout, verstr)
    assert _estimators(row) == []
    assert row["artifacts"] == []


# --- artifacts ---------------------------------------------------------------


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_two_fits_in_one_run_keep_two_artifacts_with_matching_digests(app_layout):
    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"], log_models=True)
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        LogisticRegression(C=0.5).fit(X, Y)
        LogisticRegression(C=5.0).fit(X, Y)

    row = _row(app_layout, verstr)
    names = [a["name"] for a in row["artifacts"]]
    assert names == [
        "sklearn_LogisticRegression.pkl",
        "sklearn_LogisticRegression_2.pkl",
    ]

    art_dir = _storage(app_layout).list_artifact_files(app_layout.app_name, verstr)
    entries = [e for e in row["log"] if e.get("type") == "artifact"]
    assert len(entries) == 2
    for entry in entries:
        assert entry["sha256"] == _sha256(os.path.join(art_dir, entry["path"]))


# --- configuration -----------------------------------------------------------


def test_log_models_is_off_by_default(app_layout):
    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"])
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        LogisticRegression().fit(X, Y)

    row = _row(app_layout, verstr)
    assert row["params"]["sklearn_estimator"] == "LogisticRegression"
    assert row["artifacts"] == []


def test_a_second_autolog_call_reconfigures(app_layout):
    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"], log_models=True)
    autolog(frameworks=["sklearn"], log_models=False)
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        LogisticRegression().fit(X, Y)

    assert _row(app_layout, verstr)["artifacts"] == []


# --- imports -----------------------------------------------------------------

_HEAVY = ("tensorflow", "torch", "lightning", "pytorch_lightning", "xgboost", "keras")

_PROBE = """
import sys
from version_stamp.exp import autolog
from version_stamp.exp.autolog import _PATCH_MARKER
autolog()
heavy = sorted(m for m in {heavy!r} if m in sys.modules)
from sklearn.linear_model import LogisticRegression
owner = next(k for k in LogisticRegression.__mro__ if "fit" in vars(k))
print("HEAVY", heavy)
print("PATCHED", getattr(vars(owner)["fit"], _PATCH_MARKER, None) is not None)
"""


def test_autolog_imports_no_framework_the_script_did_not_import():
    """A sklearn-only script must not pay for TensorFlow, torch and friends."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(
        [sys.executable, "-c", _PROBE.format(heavy=_HEAVY)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stderr
    assert "HEAVY []" in out.stdout, out.stdout
    # ...and the framework imported *after* autolog() is still patched.
    assert "PATCHED True" in out.stdout, out.stdout
