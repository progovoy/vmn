"""Snapshot capture for ``start_run`` in a sweep: outside the lock, once per state.

A sweep starts N trials at once. Capturing the snapshot (git diff, format-patch,
hashing and tarring untracked files) under the repo lock serialized them all;
only claiming the verstr needs the lock. Within one process, trials 2..N reuse
the snapshot trial 1 captured while the tree has not changed, and
``snapshot=False`` records the code identity without any payload.
"""
import os
import subprocess

import pytest
from helpers import _PROJECT_ROOT, _PY, _bootstrap, _storage

from version_stamp.cli import snapshot as snap
from version_stamp.exp import start_run

N_WORKERS = 8
JOIN_TIMEOUT = 240


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)


def _write(app_layout, name, content):
    with open(os.path.join(app_layout.repo_path, name), "w") as f:
        f.write(content)


def _record(app_layout, verstr):
    return _storage(app_layout).load(app_layout.app_name, verstr)


# ---------------------------------------------------------------------------
# concurrency: captures overlap across processes
# ---------------------------------------------------------------------------

# Wraps the capture in a barrier: each worker announces it is inside and waits
# (bounded) for another worker to be inside too. Under a lock held across the
# capture no two workers can ever be inside at once, so seeing one is proof.
_WORKER = """
import os, sys, time
from version_stamp.exp import capture

inside = os.environ["INSIDE_DIR"]
real = capture.capture_snapshot

def instrumented(*args, **kwargs):
    me = os.path.join(inside, str(os.getpid()))
    open(me, "w").close()
    overlapped = False
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if len(os.listdir(inside)) >= 2:
            overlapped = True
            break
        time.sleep(0.02)
    try:
        return real(*args, **kwargs)
    finally:
        os.unlink(me)
        print("OVERLAP", overlapped)

capture.capture_snapshot = instrumented

from version_stamp.exp import start_run
with start_run(os.environ["APP"]) as run:
    pass
print("RUN", run.id)
"""


def test_concurrent_start_runs_capture_in_parallel(app_layout):
    _bootstrap(app_layout)
    _write(app_layout, "untracked.txt", "data")
    inside = os.path.join(app_layout.base_dir, "inside")
    os.makedirs(inside)
    env = dict(os.environ)
    env.update(
        PYTHONPATH=os.pathsep.join(
            p for p in (_PROJECT_ROOT, os.environ.get("PYTHONPATH")) if p
        ),
        VMN_WORKING_DIR=app_layout.repo_path,
        APP=app_layout.app_name,
        INSIDE_DIR=inside,
    )
    procs = [
        subprocess.Popen(
            [_PY, "-c", _WORKER],
            cwd=app_layout.repo_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for _ in range(N_WORKERS)
    ]
    outs = [p.communicate(timeout=JOIN_TIMEOUT)[0] for p in procs]

    assert all(p.returncode == 0 for p in procs), outs
    ids = {line.split()[1] for out in outs for line in out.splitlines() if line.startswith("RUN ")}
    assert len(ids) == N_WORKERS
    assert any("OVERLAP True" in out for out in outs), (
        "no two snapshot captures ever ran at the same time - the capture is "
        "still serialized on the repo lock"
    )


# ---------------------------------------------------------------------------
# per-process memo
# ---------------------------------------------------------------------------


@pytest.fixture
def tarballs(monkeypatch):
    calls = []
    real = snap._collect_untracked_tarball

    def spy(repo_path):
        calls.append(repo_path)
        return real(repo_path)

    monkeypatch.setattr(snap, "_collect_untracked_tarball", spy)
    return calls


def test_trials_in_one_process_reuse_the_captured_snapshot(app_layout, tarballs):
    _bootstrap(app_layout)
    _write(app_layout, "untracked.txt", "data")

    with start_run(app_layout.app_name) as first:
        pass
    with start_run(app_layout.app_name) as second:
        pass

    assert len(tarballs) == 1
    for verstr in (first.id, second.id):
        meta, patches = _record(app_layout, verstr)
        assert meta["has_untracked_files"] is True
        assert patches["untracked_files"]
    assert _record(app_layout, first.id)[0]["diff_hash"] == (
        _record(app_layout, second.id)[0]["diff_hash"]
    )


def test_a_changed_tree_is_captured_again(app_layout, tarballs):
    _bootstrap(app_layout)
    _write(app_layout, "untracked.txt", "data")
    with start_run(app_layout.app_name) as first:
        pass

    _write(app_layout, "untracked.txt", "changed data")
    with start_run(app_layout.app_name) as second:
        pass

    assert len(tarballs) == 2
    assert _record(app_layout, first.id)[0]["diff_hash"] != (
        _record(app_layout, second.id)[0]["diff_hash"]
    )


# ---------------------------------------------------------------------------
# snapshot=False
# ---------------------------------------------------------------------------


def test_snapshot_false_records_identity_without_payload(app_layout, tarballs):
    _bootstrap(app_layout)
    _write(app_layout, "untracked.txt", "data")
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "v1")
    _write(app_layout, "tracked.txt", "v2")

    with start_run(app_layout.app_name, snapshot=False) as light:
        pass
    with start_run(app_layout.app_name) as full:
        pass

    light_meta, light_patches = _record(app_layout, light.id)
    full_meta, _ = _record(app_layout, full.id)
    assert light_patches == {} or not any(light_patches.values())
    assert light_meta["snapshot"] is False
    assert light_meta["has_working_tree_patch"] is False
    assert light_meta["has_untracked_files"] is False
    assert light_meta["base_commit"] == full_meta["base_commit"]
    assert light_meta["diff_hash"] == full_meta["diff_hash"]
    assert light_meta["code_verstr"] == full_meta["code_verstr"]
    assert "snapshot" not in full_meta or full_meta["snapshot"] is True
    # Only the full run built a tarball.
    assert len(tarballs) == 1
