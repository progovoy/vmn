"""find_managed_root walks up to the nearest .git/.vmn without logging."""
import pytest

from version_stamp.core import logging as vmn_logging
from version_stamp.core.utils import find_managed_root, resolve_root_path


def _exists_over(paths):
    present = set(paths)
    return lambda path: path in present


def test_returns_the_start_dir_when_it_holds_dot_git():
    exists = _exists_over({"/work/repo/.git"})

    assert find_managed_root("/work/repo", exists) == "/work/repo"


def test_returns_the_nearest_ancestor_holding_dot_vmn():
    exists = _exists_over({"/work/.git", "/work/repo/.vmn"})

    assert find_managed_root("/work/repo/a/b", exists) == "/work/repo"


def test_returns_none_at_the_filesystem_root():
    assert find_managed_root("/work/repo/a", _exists_over(set())) is None


def test_resolve_root_path_raises_runtime_error_with_no_logger_installed(
    tmp_path, monkeypatch
):
    saved = vmn_logging._logger_holder[0]
    vmn_logging.reset_logger()
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))
    try:
        with pytest.raises(RuntimeError, match="Running from an unmanaged directory"):
            resolve_root_path()
    finally:
        vmn_logging._logger_holder[0] = saved
