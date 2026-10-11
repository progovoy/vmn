"""The submission hint's target — the run just claimed — is read from what the
command wrote locally, never from a remote store (whose listings no deadline
can interrupt), and carries the command ``vmn-exp run`` runs, so the hint
ranks like a later ``vmn-exp similar -v <run>``."""
import argparse
import json
import os
import sys
import time

import pytest
import yaml
from exp_helpers import _bootstrap, _exp, _storage, extract_dev_verstr
from similar_seed import TRAIN_STEP, WRITER, features, seed, verstr
from vmn_exp.cli import similar_hint
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.areas import local_store_root
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage

TRAIN = "def train_step():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return {}\n"
CHANGES = features(["train.py"], [TRAIN_STEP], author="alice@x.io")
BLOCK_SEC = 0.5


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_SWEEP_TRIAL", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_STORE", "VMN_WRITER_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(similar_hint, "BUDGET_SEC", 60.0)


def _app_with_a_dirty_tree(app_layout):
    """A committed train.py, changed in the working tree."""
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "train.py", TRAIN.format("a"))
    with open(os.path.join(app_layout.repo_path, "train.py"), "w") as f:
        f.write(TRAIN.format("b"))


def _head(err):
    """The hint's one head line in *err*."""
    [line] = [line for line in err.splitlines() if "similar run" in line]
    return line


class _UnreachableRemote:
    """A remote store that answers no call: each one is recorded, blocks
    (a slow LIST) and fails."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.calls.append(name)
            time.sleep(BLOCK_SEC)
            raise ConnectionError(f"remote {name}")
        return call


def test_the_hint_reads_the_new_run_from_the_local_side_only(app_layout, capfd):
    _app_with_a_dirty_tree(app_layout)
    app = app_layout.app_name
    prior = seed(_storage(app_layout), app, verstr(1, commit="0000000"), changes=CHANGES)
    assert _exp(app, action="list") == 0
    capfd.readouterr()
    assert _exp(app, extra_args=["--no-similar"]) == 0
    new = extract_dev_verstr(capfd.readouterr().out)
    remote = _UnreachableRemote()
    local = LocalSnapshotStorage(local_store_root(app_layout.repo_path), "runs")
    storage = CachedSnapshotStorage(local, remote)

    similar_hint.print_hint(storage, app, new, argparse.Namespace(), {})

    line = _head(capfd.readouterr().err)
    assert line.startswith(f"1 similar run: closest — {prior} by alice@x.io, ")
    assert remote.calls == []


@pytest.fixture
def bucket(monkeypatch):
    from s3_helpers import mocked_bucket
    from vmn_exp.storage import buffered

    with mocked_bucket(monkeypatch):
        yield
        buffered.close_all()


def test_over_a_direct_remote_store_the_hint_reads_the_new_run_from_its_log_buffer(
        bucket, capfd):
    from s3_helpers import BUCKET, PREFIX, record_calls
    from vmn_exp.core.index import indexed_snapshot
    from vmn_exp.snapshot import open_storage
    from vmn_exp.storage.uri import s3_uri

    storage = open_storage(s3_uri(BUCKET, PREFIX), area="runs", buffer_logs=True)
    prior = seed(storage, "app", verstr(1), changes=CHANGES)
    storage.sync_log_to_remote("app", prior, WRITER)
    indexed_snapshot(storage, "app", wait=True)
    # Its features entry is not shipped yet: only the buffer holds it.
    new = seed(storage, "app", verstr(2), changes=CHANGES)
    calls = record_calls(storage._remote._s3)
    capfd.readouterr()

    similar_hint.print_hint(storage, "app", new, argparse.Namespace(), {})

    line = _head(capfd.readouterr().err)
    assert line.startswith(f"1 similar run: closest — {prior} by alice@x.io, ")
    assert "train_step" in line
    assert calls == []


def _prior_of(storage, app, n, script, ts):
    """A finished past run of *script* that changed train_step."""
    v = seed(storage, app, verstr(n, commit="0000000"), ts=ts, changes=CHANGES)
    storage.save_file(app, v, RUN_STATE_FILE, yaml.safe_dump({
        "state": "finished", "command": [sys.executable, script], "pid": 1, "host": "h",
        "started_at": ts, "heartbeat": ts, "heartbeat_interval_sec": 30, "exit_code": 0}))
    return v


def _ranked(err, verstrs):
    """*verstrs* in the order the lines of *err* (the hint's) name them."""
    return [v for line in err.splitlines() for v in verstrs if v in line]


def test_the_run_hint_ranks_by_the_command_like_similar_on_the_run(app_layout, capfd,
                                                                    tmp_path):
    _app_with_a_dirty_tree(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    train = _prior_of(storage, app, 1, "train.py", "2026-01-01T00:00:00Z")
    # Newer: without the command it would rank first.
    other = _prior_of(storage, app, 2, "eval.py", "2026-01-02T00:00:00Z")
    assert _exp(app, action="list") == 0
    script = tmp_path / "train.py"
    script.write_text("pass\n")
    capfd.readouterr()

    code = _exp(app, action="run", extra_args=["--no-system-metrics"],
                run_cmd=[sys.executable, str(script), "--lr", "0.1"])

    out = capfd.readouterr()
    assert code == 0, out.err
    hinted = _ranked(out.err, (train, other))
    new = extract_dev_verstr(out.out)
    assert _exp(app, action="similar", extra_args=["-v", new, "--json"]) == 0
    items = json.loads(capfd.readouterr().out)
    assert hinted == [item["verstr"] for item in items] == [train, other]
