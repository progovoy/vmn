"""``vmn-exp create`` hands the repo lock back before its submission hint
reads the index, as ``vmn-exp run`` does before supervising: the hint never
holds up another vmn command."""
import sys

from exp_helpers import _bootstrap, _exp
from filelock import Timeout
from version_stamp.api import get_repo_lock, resolve_root_path
from vmn_exp.cli import similar_hint


def _repo_lock_free():
    lock = get_repo_lock(resolve_root_path())
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return False
    lock.release()
    return True


def _spy_hint(monkeypatch):
    seen = []
    real = similar_hint.print_hint

    def hint(*args, **kwargs):
        seen.append(_repo_lock_free())
        return real(*args, **kwargs)

    monkeypatch.setattr(similar_hint, "print_hint", hint)
    return seen


def test_create_releases_the_repo_lock_before_the_hint(app_layout, monkeypatch):
    _bootstrap(app_layout)
    seen = _spy_hint(monkeypatch)
    assert _exp(app_layout.app_name) == 0
    assert seen == [True]


def test_run_releases_the_repo_lock_before_the_hint(app_layout, monkeypatch):
    _bootstrap(app_layout)
    seen = _spy_hint(monkeypatch)
    assert _exp(app_layout.app_name, action="run", run_cmd=[sys.executable, "-c", "pass"]) == 0
    assert seen == [True]
