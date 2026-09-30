"""The git execute patch logs big stdout/stderr truncated unless --debug."""
import logging

import pytest

from island_helpers import _commit, _git
from version_stamp.backends.git import GitBackend
from version_stamp.core.constants import VMN_USER_NAME
from version_stamp.core.logging import (
    clear_logger_handlers,
    init_stamp_logger,
    reset_logger,
)

SECRET_URL = "https://user:s3cret@example.com/r.git"
BIG = SECRET_URL + "\n" + "x" * 20000 + "TAIL_MARKER"


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "big.txt", BIG)
    yield tmp_path
    clear_logger_handlers(logging.getLogger(VMN_USER_NAME))
    clear_logger_handlers(logging.getLogger())
    reset_logger()


def _log_of_big_git_output(repo, debug):
    log_path = repo / "vmn.log"
    init_stamp_logger(str(log_path), debug=debug, supress_stdout=True)
    GitBackend(str(repo))._be.git.show("HEAD:big.txt")
    return log_path.read_text()


def test_big_output_is_truncated_in_the_log_file(repo):
    log = _log_of_big_git_output(repo, debug=False)

    assert "show HEAD:big.txt" in log
    assert "return code: 0" in log
    assert "bytes truncated" in log
    assert "TAIL_MARKER" not in log
    assert "x" * 20000 not in log


def test_big_output_is_kept_in_full_with_debug(repo):
    log = _log_of_big_git_output(repo, debug=True)

    assert "TAIL_MARKER" in log
    assert "bytes truncated" not in log


@pytest.mark.parametrize("debug", [False, True])
def test_url_credentials_are_still_scrubbed(repo, debug):
    log = _log_of_big_git_output(repo, debug=debug)

    assert "s3cret" not in log
    assert "https://***@example.com/r.git" in log
