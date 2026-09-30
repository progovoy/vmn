"""A publish that fails at any stage (writing files, the vmn commit, the tag,
the push) returns that stage's code and leaves the tree, HEAD and tags exactly
as they were before the stamp or first init-app."""
import subprocess

import pytest
from helpers import _init_app, _run_vmn_init, _stamp_app, reset_logger, vmn_run
from version_stamp.backends.git import GitBackend
from version_stamp.stamping.publisher import VersionControlStamper


def _git(app_layout, *args):
    return subprocess.run(
        ["git", *args],
        cwd=app_layout.repo_path, check=True, capture_output=True, text=True,
    ).stdout


def _repo_state(app_layout):
    return {
        "status": _git(app_layout, "status", "--porcelain", "--untracked-files=all"),
        "head": _git(app_layout, "rev-parse", "HEAD"),
        "tags": set(_git(app_layout, "tag", "-l").split()),
    }


def _fail_after(cls, name):
    real = getattr(cls, name)

    def failing(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError(f"forced {name} failure")

    return failing


def _always_fail(*args, **kwargs):
    raise RuntimeError("forced push failure")


STAGES = {
    "write": (VersionControlStamper, "write_version_to_file", -1),
    "commit": (VersionControlStamper, "publish_commit", 3),
    "tag": (GitBackend, "tag", 1),
    "push": (GitBackend, "push", 2),
}


@pytest.fixture
def publish_codes(monkeypatch):
    """The err each publish_stamp call hands its caller (a raise becomes -1)."""
    codes = []
    real = VersionControlStamper.publish_stamp

    def spy(self, *args, **kwargs):
        try:
            err = real(self, *args, **kwargs)
        except Exception:
            codes.append(-1)
            raise
        codes.append(err)
        return err

    monkeypatch.setattr(VersionControlStamper, "publish_stamp", spy)
    return codes


def _force_failure(monkeypatch, stage):
    cls, name, code = STAGES[stage]
    failing = _always_fail if stage == "push" else _fail_after(cls, name)
    monkeypatch.setattr(cls, name, failing)
    return code


@pytest.mark.parametrize("stage", list(STAGES))
def test_failed_stamp_returns_the_stage_code_and_restores_the_tree(
    app_layout, monkeypatch, publish_codes, stage
):
    app = app_layout.app_name
    _run_vmn_init()
    assert _init_app(app)[0] == 0
    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")
    before = _repo_state(app_layout)
    code = _force_failure(monkeypatch, stage)
    publish_codes.clear()

    err, _, _ = _stamp_app(app, "patch")

    assert err != 0
    assert publish_codes and set(publish_codes) == {code}
    assert _repo_state(app_layout) == before


@pytest.mark.parametrize("stage", list(STAGES))
def test_failed_first_init_app_returns_the_stage_code_and_restores_the_tree(
    app_layout, monkeypatch, publish_codes, stage
):
    app = app_layout.app_name
    _run_vmn_init()
    before = _repo_state(app_layout)
    code = _force_failure(monkeypatch, stage)

    reset_logger()
    ret, _ = vmn_run(["init-app", app])

    assert ret == 1
    assert publish_codes == [code]
    assert _repo_state(app_layout) == before
