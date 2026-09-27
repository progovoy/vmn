"""Tests for version_stamp.core.repo_lock (Phase 1 step b)."""
import os
import subprocess
import sys


def test_env_override_path(monkeypatch, tmp_path):
    """VMN_LOCK_FILE_PATH overrides the default lock path."""
    from version_stamp.core.repo_lock import get_repo_lock

    monkeypatch.setenv("VMN_LOCK_FILE_PATH", str(tmp_path / "shared.lock"))
    lock = get_repo_lock("/somewhere/else")
    assert lock.lock_file == str(tmp_path / "shared.lock")


def test_default_lock_path(monkeypatch, tmp_path):
    """Default lock path is .vmn/vmn.lock inside vmn_root_path."""
    from version_stamp.core.repo_lock import get_repo_lock

    monkeypatch.delenv("VMN_LOCK_FILE_PATH", raising=False)
    lock = get_repo_lock(str(tmp_path))
    assert lock.lock_file == os.path.join(str(tmp_path), ".vmn", "vmn.lock")


def test_writer_reexport_is_same_object():
    """experiment_writer.get_repo_lock is the same object as repo_lock.get_repo_lock."""
    from vmn_exp.core.writer import get_repo_lock as ew_lock
    from version_stamp.core.repo_lock import get_repo_lock as rl_lock

    assert ew_lock is rl_lock


def test_repo_lock_module_imports_no_experiment_modules():
    """Importing repo_lock must not pull in any experiment/exp/ui modules."""
    code = (
        "import sys; "
        "import version_stamp.core.repo_lock; "
        "bad = [m for m in sys.modules if any("
        "    m.startswith(p) for p in ("
        "        'version_stamp.core.experiment_',"
        "        'vmn_exp.sdk',"
        "        'vmn_exp.ui',"
        "        'vmn_exp',"
        "    )"
        ")]; "
        "print(bad); "
        "raise SystemExit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"repo_lock pulled in experiment/exp/ui modules: {result.stdout.strip()}"
    )
