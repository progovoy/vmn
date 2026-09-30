"""vmn-exp's writer lock is vmn's repo lock (moved from the core suite's
test_repo_lock.py)."""


def test_writer_lock_guards_the_same_file(tmp_path, monkeypatch):
    """The experiment writer's lock (vmn_exp._base's copy) and vmn's are one file."""
    from vmn_exp.core.writer import get_repo_lock as ew_lock
    from version_stamp.core.repo_lock import get_repo_lock as rl_lock

    monkeypatch.delenv("VMN_LOCK_FILE_PATH", raising=False)
    assert ew_lock(str(tmp_path)).lock_file == rl_lock(str(tmp_path)).lock_file
