"""An SDK run compacts its metric stream into ``metrics/<w>.vmx`` when it
finishes (plan 12 §6); past the final-upload deadline the stream stays."""
import os
import subprocess
import threading
import time

from exp_helpers import _PY, _SRC_PATH

from vmn_exp.core.metric_files import indexed_name, is_stream_file
from vmn_exp.core.writer import get_writer_id
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


def _storage(root, cls=CachedSnapshotStorage):
    st = cls(LocalSnapshotStorage(str(root), area="runs"))
    st.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


def _names(st):
    return [n for objs in st.metric_objects(APP, VERSTR).values() for n, _ in objs]


def _steps(st):
    log = LocalSnapshotStorage(st._local.root, "runs").load_merged_log(APP, VERSTR)
    return [e["step"] for e in log if e.get("type") == "metrics" and "loss" in e["values"]]


def _log(run, n=30):
    for step in range(n):
        run.log_metric("loss", step / 3, step=step)


def test_finish_leaves_only_the_indexed_file(tmp_path):
    st = _storage(tmp_path)
    run = Run(st, APP, VERSTR, 60)
    run._open()
    _log(run)
    run.finish()
    assert _names(st) == [indexed_name(get_writer_id())]
    assert _steps(st) == list(range(30))


class _StuckIndexing(CachedSnapshotStorage):
    release = threading.Event()

    def put_indexed(self, *args, **kwargs):
        self.release.wait(30)
        return super().put_indexed(*args, **kwargs)


def test_past_the_deadline_the_stream_stays(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC", "0.5")
    st = _storage(tmp_path, _StuckIndexing)
    run = Run(st, APP, VERSTR, 60)
    run._open()
    _log(run)
    started = time.monotonic()
    run.finish()
    try:
        assert time.monotonic() - started < 10
        names = _names(st)
        assert names and all(is_stream_file(n) for n in names)
        assert _steps(st) == list(range(30))
    finally:
        _StuckIndexing.release.set()


_SCRIPT = """
import sys
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.sdk.run import Run
st = CachedSnapshotStorage(LocalSnapshotStorage(sys.argv[1], area="runs"))
run = Run(st, "app", "0.0.1-dev.aaaaaaa.bbbbbbb", 3600)
run._open()
for step in range(25):
    run.log_metric("loss", 0.5, step=step)
"""


def test_interpreter_exit_compacts_too(tmp_path):
    st = _storage(tmp_path)
    env = dict(os.environ, PYTHONPATH=_SRC_PATH, VMN_WRITER_ID="child")
    subprocess.run([_PY, "-c", _SCRIPT, str(tmp_path)], env=env, check=True, timeout=60)
    assert _names(st) == [indexed_name("child")]
    assert _steps(st) == list(range(25))
