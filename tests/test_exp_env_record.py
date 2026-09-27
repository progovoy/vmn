"""Env capture wiring for experiment records (D6/D7).

Verifies:
- create_run writes env_summary into the run's template and env.yml next to it.
- Capture failures never fail create.
- Default is on; opt-outs work (arg > env-var > conf).
- CLI --no-env skips capture.
- ``vmn exp run`` probes the child python interpreter.
- snapshot-metadata mode captures env.
- Resume keeps the original env (no re-capture).
- Capture happens outside the repo lock.

No Docker required — unit tests drive fake storage and monkeypatch
real storage for integration; app_layout tests create actual git repos.
"""
import logging
import os
import threading
import types

import pytest
import yaml


# ---------------------------------------------------------------------------
# Shared fake storage helpers (duck-typed)
# ---------------------------------------------------------------------------

class _FakeStorage:
    """Minimal duck-typed storage for experiment_writer.create_run."""

    def __init__(self):
        self.files = {}
        self.log_entries = []
        self._snapshots = []
        self.saved = {}

    def save_file(self, app_name, verstr, name, content):
        self.files[(app_name, verstr, name)] = content

    def load_file(self, app_name, verstr, name):
        return self.files.get((app_name, verstr, name))

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        self.log_entries.append((app_name, verstr, writer_id, entry))

    def list_snapshots(self, app_name):
        return self._snapshots

    def exists(self, app_name, verstr):
        return verstr in self.saved

    def save(self, app_name, verstr, metadata, patches):
        self.saved[verstr] = (metadata, patches)
        self._snapshots.append(metadata)


@pytest.fixture(autouse=True)
def _clean_writer_id(monkeypatch):
    from vmn_exp.core import writer as experiment_writer

    experiment_writer._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    yield
    experiment_writer._WRITER_ID = None


# ---------------------------------------------------------------------------
# 1. Writes env.yml and summary into metadata
# ---------------------------------------------------------------------------

def test_writes_env_yml_and_summary():
    from vmn_exp.core.env import capture_env
    from vmn_exp.core.writer import create_run

    env = capture_env()
    storage = _FakeStorage()
    template = {"app_name": "myapp", "timestamp": "2026-01-01T00:00:00Z"}
    verstr = create_run(
        storage, "myapp", "0.0.1-dev.abc.def", template, {}, env=env
    )

    # Full env.yml must be written next to the record.
    env_key = ("myapp", verstr, "env.yml")
    assert env_key in storage.files, "env.yml missing from storage"
    stored = yaml.safe_load(storage.files[env_key])
    assert "packages" in stored
    assert "python" in stored

    # The compact summary must appear inside the metadata.
    metadata, _ = storage.saved[verstr]
    assert "env" in metadata, "env summary missing from metadata"
    summary = metadata["env"]
    assert "python" in summary
    assert "packages_count" in summary
    assert "packages_sha" in summary


# ---------------------------------------------------------------------------
# 2. Capture failure never fails create
# ---------------------------------------------------------------------------

def test_capture_failure_never_fails_create(monkeypatch):
    """A storage error writing env.yml must not prevent the run from being created.

    Also verifies that when capture_env() itself raises in the create flow,
    the run is still created (tested via _capture_env_safe in exp/create.py).
    """
    from vmn_exp.core.env import capture_env
    from vmn_exp.core.writer import create_run

    env = capture_env()
    storage = _FakeStorage()

    # Make save_file raise when asked to write env.yml.
    _orig = storage.save_file

    def _failing_save(app_name, verstr, name, content):
        if name == "env.yml":
            raise OSError("disk full")
        return _orig(app_name, verstr, name, content)

    storage.save_file = _failing_save

    template = {"app_name": "myapp", "timestamp": "2026-01-01T00:00:00Z"}
    # Must not raise.
    verstr = create_run(
        storage, "myapp", "0.0.1-dev.abc.def", template, {}, env=env
    )
    assert verstr is not None
    assert verstr in storage.saved
    env_key = ("myapp", verstr, "env.yml")
    assert env_key not in storage.files


# ---------------------------------------------------------------------------
# 3. Captures by default (start_run, no override)
# ---------------------------------------------------------------------------

def test_captures_by_default(app_layout):
    from helpers import _bootstrap, _storage
    from version_stamp.exp import start_run

    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        verstr = run.id

    st = _storage(app_layout)
    # env.yml should be present
    raw = st.load_file(app_layout.app_name, verstr, "env.yml")
    assert raw is not None, "env.yml not written by default"
    # summary must be in metadata
    meta, _ = st.load(app_layout.app_name, verstr)
    assert "env" in meta


# ---------------------------------------------------------------------------
# 4. capture_env=False skips capture
# ---------------------------------------------------------------------------

def test_capture_env_false(app_layout):
    from helpers import _bootstrap, _storage
    from version_stamp.exp import start_run

    _bootstrap(app_layout)
    with start_run(app_layout.app_name, capture_env=False) as run:
        verstr = run.id

    st = _storage(app_layout)
    raw = st.load_file(app_layout.app_name, verstr, "env.yml")
    assert raw is None, "env.yml written despite capture_env=False"
    meta, _ = st.load(app_layout.app_name, verstr)
    assert "env" not in meta


# ---------------------------------------------------------------------------
# 5. conf opt-out: experiment.capture_env: false
# ---------------------------------------------------------------------------

def test_conf_opt_out(app_layout):
    from helpers import _bootstrap, _storage
    from version_stamp.exp import start_run

    _bootstrap(app_layout)

    # Write conf with experiment.capture_env: false.
    # The conf.yml structure has a top-level "conf:" key.
    conf_path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml"
    )
    with open(conf_path) as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("conf", {}).setdefault("experiment", {})["capture_env"] = False
    with open(conf_path, "w") as f:
        yaml.dump(data, f)

    with start_run(app_layout.app_name) as run:
        verstr = run.id

    st = _storage(app_layout)
    raw = st.load_file(app_layout.app_name, verstr, "env.yml")
    assert raw is None, "env.yml written despite conf capture_env: false"
    meta, _ = st.load(app_layout.app_name, verstr)
    assert "env" not in meta


# ---------------------------------------------------------------------------
# 6. env-var opt-out: VMN_CAPTURE_ENV=0
# ---------------------------------------------------------------------------

def test_env_var_opt_out(app_layout, monkeypatch):
    from helpers import _bootstrap, _storage
    from version_stamp.exp import start_run

    _bootstrap(app_layout)
    monkeypatch.setenv("VMN_CAPTURE_ENV", "0")
    with start_run(app_layout.app_name) as run:
        verstr = run.id

    st = _storage(app_layout)
    raw = st.load_file(app_layout.app_name, verstr, "env.yml")
    assert raw is None, "env.yml written despite VMN_CAPTURE_ENV=0"
    meta, _ = st.load(app_layout.app_name, verstr)
    assert "env" not in meta


# ---------------------------------------------------------------------------
# 7. arg overrides conf: capture_env=True beats conf capture_env: false
# ---------------------------------------------------------------------------

def test_arg_overrides_conf(app_layout):
    from helpers import _bootstrap, _storage
    from version_stamp.exp import start_run

    _bootstrap(app_layout)

    # Write conf with experiment.capture_env: false.
    conf_path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml"
    )
    with open(conf_path) as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("conf", {}).setdefault("experiment", {})["capture_env"] = False
    with open(conf_path, "w") as f:
        yaml.dump(data, f)

    # explicit True beats conf False
    with start_run(app_layout.app_name, capture_env=True) as run:
        verstr = run.id

    st = _storage(app_layout)
    raw = st.load_file(app_layout.app_name, verstr, "env.yml")
    assert raw is not None, "env.yml missing — arg True did not override conf False"


# ---------------------------------------------------------------------------
# 8. CLI --no-env skips capture
# ---------------------------------------------------------------------------

def test_cli_no_env(app_layout):
    from helpers import _bootstrap, _storage, _experiment

    _bootstrap(app_layout)
    ret = _experiment(
        app_layout.app_name, action="create", extra_args=["--no-env"]
    )
    assert ret == 0
    st = _storage(app_layout)
    runs = list(st.list_snapshots(app_layout.app_name))
    assert runs, "no experiments found"
    last_verstr = runs[-1]["verstr"] if isinstance(runs[-1], dict) else runs[-1]
    raw = st.load_file(app_layout.app_name, last_verstr, "env.yml")
    assert raw is None, "env.yml written despite --no-env"
    meta, _ = st.load(app_layout.app_name, last_verstr)
    assert "env" not in meta


# ---------------------------------------------------------------------------
# 9. vmn exp run probes child python interpreter
# ---------------------------------------------------------------------------

def test_run_probes_child_python(app_layout, monkeypatch, tmp_path):
    from helpers import _bootstrap, _storage
    from vmn_exp.core import env as experiment_env

    _bootstrap(app_layout)

    probed = []

    def _fake_from_interpreter(exe, timeout=5):
        probed.append(exe)
        return {
            "python": {"version": "3.x.y", "implementation": "CPython",
                       "executable": exe},
            "platform": {"system": "Linux", "machine": "x86_64",
                         "release": "5.15.0"},
            "hostname": "test-host",
            "packages": {"pytest": "7.0.0"},
            "source": "child-interpreter",
        }

    monkeypatch.setattr(experiment_env, "env_from_interpreter", _fake_from_interpreter)

    import sys
    from helpers import _storage

    # Write a minimal python script that does nothing.
    script = tmp_path / "noop.py"
    script.write_text("import sys; sys.exit(0)\n")

    from helpers import _experiment
    _experiment(
        app_layout.app_name,
        action="run",
        run_cmd=[sys.executable, str(script)],
    )

    st = _storage(app_layout)
    runs = list(st.list_snapshots(app_layout.app_name))
    assert runs, "no experiment run found"
    last = runs[-1]["verstr"] if isinstance(runs[-1], dict) else runs[-1]

    raw = st.load_file(app_layout.app_name, last, "env.yml")
    assert raw is not None, "env.yml not written for python child"
    stored = yaml.safe_load(raw)
    # env_from_interpreter was called (because the child is a python interpreter)
    assert probed, "env_from_interpreter was not called for a python child"
    meta, _ = st.load(app_layout.app_name, last)
    assert "env" in meta


# ---------------------------------------------------------------------------
# 10. snapshot-metadata mode captures env
# ---------------------------------------------------------------------------

def test_snapshot_meta_mode_captures(tmp_path, monkeypatch):
    """git-free (VMN_SNAPSHOT_METADATA) mode still captures env."""
    from vmn_exp.core.env import capture_env
    from vmn_exp.core.from_snapshot import create_from_snapshot
    from vmn_exp.snapshot import get_snapshot_storage

    # Build minimal vmn_metadata.yml
    meta_path = tmp_path / "vmn_metadata.yml"
    meta_path.write_text(
        "verstr: 0.0.1-dev.abc.def\napp_name: testapp\n"
        "base_version: 0.0.1\nbase_commit: abc\nbranch: master\n"
    )

    storage = get_snapshot_storage(
        "local", vmn_root_path=str(tmp_path / "exp"), subdir="experiments"
    )

    env = capture_env()
    verstr, err = create_from_snapshot(
        storage, "testapp", str(meta_path), env=env
    )
    assert err is None, f"create_from_snapshot failed: {err}"
    assert verstr is not None

    raw = storage.load_file("testapp", verstr, "env.yml")
    assert raw is not None, "env.yml not written in snapshot-meta mode"
    meta, _ = storage.load("testapp", verstr)
    assert "env" in meta


# ---------------------------------------------------------------------------
# 11. Resume keeps original env (no re-capture)
# ---------------------------------------------------------------------------

def test_resume_keeps_env(app_layout, monkeypatch):
    from helpers import _bootstrap, _storage
    from vmn_exp.core import env as experiment_env
    from version_stamp.exp import start_run

    _bootstrap(app_layout)

    captured_calls = []
    original_capture = experiment_env.capture_env

    def _counting_capture():
        captured_calls.append(1)
        return original_capture()

    monkeypatch.setattr(experiment_env, "capture_env", _counting_capture)

    # First run — creates the record; env should be captured once.
    with start_run(app_layout.app_name) as run:
        verstr = run.id

    assert len(captured_calls) == 1

    # Resume the same run — env must NOT be re-captured.
    captured_calls.clear()
    with start_run(app_layout.app_name, run_id=verstr) as run2:
        assert run2.id == verstr

    assert len(captured_calls) == 0, "env captured again on resume"


# ---------------------------------------------------------------------------
# 12. Capture happens outside the repo lock
# ---------------------------------------------------------------------------

def test_capture_outside_lock(app_layout, monkeypatch):
    """env capture must complete before the repo lock is acquired."""
    from helpers import _bootstrap
    from vmn_exp.core import env as experiment_env
    from version_stamp.core import repo_lock as _repo_lock_mod
    from version_stamp.exp import start_run

    _bootstrap(app_layout)

    order = []

    original_capture = experiment_env.capture_env

    def _spy_capture():
        order.append("capture")
        return original_capture()

    # Monkey-patch the lock's acquire via the context manager.
    original_lock = _repo_lock_mod.get_repo_lock

    def _spy_lock(path, **kw):
        ctx = original_lock(path, **kw)

        class _SpyCtx:
            def __enter__(self):
                order.append("lock")
                return ctx.__enter__()

            def __exit__(self, *args):
                return ctx.__exit__(*args)

        return _SpyCtx()

    import version_stamp.exp.create as _exp_create

    monkeypatch.setattr(experiment_env, "capture_env", _spy_capture)
    monkeypatch.setattr(_repo_lock_mod, "get_repo_lock", _spy_lock)
    monkeypatch.setattr(_exp_create, "get_repo_lock", _spy_lock)

    with start_run(app_layout.app_name) as run:
        pass

    assert "capture" in order, "capture_env was never called"
    assert "lock" in order, "repo lock was never acquired"
    capture_idx = next(i for i, v in enumerate(order) if v == "capture")
    lock_idx = next(i for i, v in enumerate(order) if v == "lock")
    assert capture_idx < lock_idx, (
        f"capture ({capture_idx}) must happen before lock ({lock_idx}); order={order}"
    )
