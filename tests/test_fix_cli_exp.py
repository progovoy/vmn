"""CLI `vmn exp` fixes: lock-free reads, @N-stable list numbers, show/compare
robustness and the conf-supplied writer id."""
import glob
import os
import re
import subprocess
import time

import pytest
import yaml
from filelock import FileLock
from helpers import _PROJECT_ROOT, _PY, _bootstrap, _exp, _storage

from version_stamp.cli.snapshot import _resolve_verstr

BLOCKED_WINDOW = 3.0
JOIN_TIMEOUT = 120


def _env(app_layout):
    env = dict(os.environ)
    env["VMN_WORKING_DIR"] = app_layout.repo_path
    env["PYTHONPATH"] = _PROJECT_ROOT
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_LOCK_FILE_PATH"):
        env.pop(key, None)
    env.pop("VMN_WRITER_ID", None)
    return env


def _popen(app_layout, argv):
    return subprocess.Popen(
        [_PY, "-m", "version_stamp.cli.entry"] + list(argv),
        cwd=app_layout.repo_path,
        env=_env(app_layout),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _join(proc, what):
    try:
        out, _ = proc.communicate(timeout=JOIN_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail(f"{what} did not finish within {JOIN_TIMEOUT}s (blocked on the lock?)")
    return proc.returncode, out


def _create(app_layout, *extra):
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


# ---------------------------------------------------------------------------
# read-only commands do not take the repo lock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["exp", "list"],
        ["exp", "show"],
        ["exp", "compare"],
        ["snapshot", "list"],
    ],
)
def test_read_only_commands_do_not_wait_for_the_repo_lock(app_layout, argv):
    _bootstrap(app_layout)
    _create(app_layout, "--metrics", "loss=1")
    _create(app_layout, "--metrics", "loss=2")

    lock = FileLock(os.path.join(app_layout.repo_path, ".vmn", "vmn.lock"))
    lock.acquire()
    try:
        proc = _popen(app_layout, argv + [app_layout.app_name])
        rc, out = _join(proc, " ".join(argv))
    finally:
        lock.release()
    assert rc == 0, out


def test_mutating_create_still_waits_for_the_repo_lock(app_layout):
    _bootstrap(app_layout)
    lock = FileLock(os.path.join(app_layout.repo_path, ".vmn", "vmn.lock"))
    lock.acquire()
    try:
        proc = _popen(app_layout, ["exp", "create", app_layout.app_name])
        time.sleep(BLOCKED_WINDOW)
        assert proc.poll() is None, "exp create ran while the lock was held"
    finally:
        lock.release()
    rc, out = _join(proc, "exp create")
    assert rc == 0, out


# ---------------------------------------------------------------------------
# list numbers are the @N storage index
# ---------------------------------------------------------------------------

_ROW_RE = re.compile(r"^(\s*)\[(\d+)\]\s+(\S+)")


def _listed(capfd, app_name, **kwargs):
    capfd.readouterr()
    assert _exp(app_name, action="list", **kwargs) == 0
    rows = []
    for line in capfd.readouterr().out.splitlines():
        m = _ROW_RE.match(line)
        if m:
            rows.append((len(m.group(1)), int(m.group(2)), m.group(3)))
    return rows


def test_sorted_list_numbers_resolve_with_at_n(app_layout, capfd):
    _bootstrap(app_layout)
    for loss in ("0.3", "0.1", "0.2"):
        _create(app_layout, "--metrics", f"loss={loss}")
    storage = _storage(app_layout)

    rows = _listed(capfd, app_layout.app_name, sort="loss")
    assert len(rows) == 3
    for _, idx, verstr in rows:
        resolved, err = _resolve_verstr(storage, app_layout.app_name, f"@{idx}")
        assert err is None and resolved == verstr, (idx, verstr, resolved)


def test_last_keeps_storage_numbers(app_layout, capfd):
    _bootstrap(app_layout)
    for loss in ("0.3", "0.1", "0.2"):
        _create(app_layout, "--metrics", f"loss={loss}")

    rows = _listed(capfd, app_layout.app_name, last=2)
    assert sorted(idx for _, idx, _ in rows) == [2, 3]


def test_tree_depth_uses_all_runs_not_just_the_shown_ones(app_layout, capfd):
    _bootstrap(app_layout)
    outer = _create(app_layout)
    inner = _create(app_layout, "--parent", outer)

    rows = _listed(capfd, app_layout.app_name, last=1)
    assert [(v, indent) for indent, _, v in rows] == [(inner, 2)]


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def _metadata_path(app_layout, verstr):
    return os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr,
        "metadata.yml",
    )


def test_show_survives_missing_base_commit_and_branch(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _create(app_layout)
    path = _metadata_path(app_layout, verstr)
    with open(path) as f:
        meta = yaml.safe_load(f)
    meta["base_commit"] = None
    meta["branch"] = None
    with open(path, "w") as f:
        yaml.dump(meta, f)

    capfd.readouterr()
    assert _exp(app_layout.app_name, action="show", version=verstr) == 0
    out = capfd.readouterr().out
    assert "Base:" in out and "(?)" in out


def _add_notes(app_layout, verstr, n):
    storage = _storage(app_layout)
    for i in range(n):
        storage.append_log_entry(
            app_layout.app_name,
            verstr,
            "notes",
            {"timestamp": f"2099-01-01T00:00:{i:02d}.000000Z", "type": "note", "text": f"n{i}"},
        )


def test_show_caps_the_printed_log(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _create(app_layout)
    _add_notes(app_layout, verstr, 60)

    capfd.readouterr()
    assert _exp(app_layout.app_name, action="show", version=verstr) == 0
    out = capfd.readouterr().out
    note_lines = [line for line in out.splitlines() if "note: n" in line]
    assert len(note_lines) == 50
    assert "note: n59" in out and "note: n9\n" not in out
    assert "earlier entries hidden" in out and "--full-log" in out


def test_show_full_log_prints_everything(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _create(app_layout)
    _add_notes(app_layout, verstr, 60)

    capfd.readouterr()
    assert (
        _exp(app_layout.app_name, action="show", version=verstr, extra_args=["--full-log"])
        == 0
    )
    out = capfd.readouterr().out
    assert len([line for line in out.splitlines() if "note: n" in line]) == 60
    assert "earlier entries hidden" not in out


# ---------------------------------------------------------------------------
# compare never loads patches
# ---------------------------------------------------------------------------


def test_compare_does_not_load_patches(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    a = _create(app_layout, "--metrics", "loss=1")
    b = _create(app_layout, "--metrics", "loss=2")

    from version_stamp.cli import snapshot

    def _no_patches(*args, **kwargs):
        raise AssertionError("compare loaded patches")

    for cls in (snapshot.LocalSnapshotStorage, snapshot.CachedSnapshotStorage):
        monkeypatch.setattr(cls, "load", _no_patches)

    capfd.readouterr()
    assert _exp(app_layout.app_name, action="compare", version=[a, b]) == 0
    out = capfd.readouterr().out
    assert "loss" in out


# ---------------------------------------------------------------------------
# conf writer_id
# ---------------------------------------------------------------------------


def test_conf_writer_id_names_the_log_file(app_layout):
    _bootstrap(app_layout)
    conf_path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml"
    )
    with open(conf_path) as f:
        conf = yaml.safe_load(f) or {}
    conf.setdefault("conf", {}).setdefault("experiment", {})["storage"] = {
        "writer_id": "confwriter"
    }
    with open(conf_path, "w") as f:
        yaml.dump(conf, f)

    rc, out = _join(
        _popen(app_layout, ["exp", "create", app_layout.app_name, "--metrics", "a=1"]),
        "exp create",
    )
    assert rc == 0, out
    logs = glob.glob(
        os.path.join(
            app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", "*",
            "log.*.jsonl",
        )
    )
    assert [os.path.basename(p) for p in logs] == ["log.confwriter.jsonl"], logs
