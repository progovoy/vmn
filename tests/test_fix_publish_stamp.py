"""publish_stamp fixes: GitHub Release prerelease flag, nested root tags,
full revert of every written file, prompt push failure, missing tag info and
AttributeErrors raised inside version backend writers."""
import json
import os
import shutil
import subprocess
import time

import pytest
import yaml
from helpers import (
    _init_app,
    _release_app,
    _run_vmn_init,
    _stamp_app,
    reset_logger,
    vmn_run,
)
from version_stamp.backends.git import GitBackend
from version_stamp.stamping import publisher
from version_stamp.stamping.publisher import VersionControlStamper


def _set_conf(app_layout, app_name, **conf):
    path = os.path.join(app_layout.repo_path, ".vmn", app_name, "conf.yml")
    with open(path) as f:
        data = yaml.safe_load(f)
    data["conf"].update(conf)
    with open(path, "w") as f:
        yaml.dump(data, f)
    app_layout._app_backend.add_conf_file(path)


def _git(app_layout, *args):
    return subprocess.run(
        ["git", *args],
        cwd=app_layout.repo_path, check=True, capture_output=True, text=True,
    ).stdout


def _tags(app_layout):
    return set(_git(app_layout, "tag", "-l").split())


def _status(app_layout):
    return _git(app_layout, "status", "--porcelain", "--untracked-files=all")


@pytest.fixture
def gh_calls(monkeypatch):
    calls = []
    real_run, real_which = subprocess.run, shutil.which

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh":
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(publisher.subprocess, "run", fake_run)
    monkeypatch.setattr(
        publisher.shutil, "which", lambda n: "/usr/bin/gh" if n == "gh" else real_which(n)
    )
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    return calls


def test_github_release_prerelease_flag_follows_the_stamped_version(
    app_layout, gh_calls
):
    app = app_layout.app_name
    _run_vmn_init()
    _init_app(app)
    _set_conf(app_layout, app, github_release={"draft": False})

    assert _stamp_app(app, "patch", prerelease="rc")[0] == 0
    assert "--prerelease" in gh_calls[-1]

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "rc2")
    err, ver_info, _ = _stamp_app(app)
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1-rc.2"
    assert "--prerelease" in gh_calls[-1]

    assert _release_app(app, stamp=True)[0] == 0
    assert gh_calls[-1][3] == f"{app}_0.0.1"
    assert "--prerelease" not in gh_calls[-1]


def test_nested_root_app_stamps_with_dashed_root_tag(app_layout):
    app = "a/b/c"
    _run_vmn_init()
    assert _init_app(app)[0] == 0

    err, ver_info, _ = _stamp_app(app, "patch")

    assert err == 0
    assert ver_info["stamping"]["root_app"]["version"] == 1
    assert {"a-b-c_0.0.1", "a-b_1"} <= _tags(app_layout)


def test_invalid_tag_name_fails_before_anything_is_written(app_layout, monkeypatch):
    app = "root_app/app1"
    _run_vmn_init()
    _init_app(app)
    head = _git(app_layout, "rev-parse", "HEAD")
    writes = []
    monkeypatch.setattr(publisher, "VMN_ROOT_TAG_REGEX", r"^never$")
    monkeypatch.setattr(
        VersionControlStamper, "write_version_to_file", lambda *a, **k: writes.append(a)
    )

    err, _, _ = _stamp_app(app, "patch")

    assert err != 0
    assert writes == []
    assert _git(app_layout, "rev-parse", "HEAD") == head


def _npm_app(app_layout):
    app = app_layout.app_name
    _run_vmn_init()
    app_layout.write_file_commit_and_push(
        "test_repo_0", "package.json", json.dumps({"version": "0.0.0"})
    )
    _init_app(app)
    _set_conf(
        app_layout, app,
        version_backends={"npm": {"path": "package.json"}},
        create_snapshots=True,
    )
    assert _stamp_app(app, "patch")[0] == 0
    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "change")
    with open(os.path.join(app_layout.repo_path, "package.json")) as f:
        return app, f.read()


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


@pytest.mark.parametrize("failing", ["publish_commit", "_generate_changelog"])
def test_failed_publish_restores_every_written_file(app_layout, monkeypatch, failing):
    app, package_json = _npm_app(app_layout)
    head = _git(app_layout, "rev-parse", "HEAD")
    monkeypatch.setattr(VersionControlStamper, failing, _boom)

    err, _, _ = _stamp_app(app, "patch")

    assert err != 0
    with open(os.path.join(app_layout.repo_path, "package.json")) as f:
        assert f.read() == package_json
    assert _status(app_layout) == ""
    assert _git(app_layout, "rev-parse", "HEAD") == head


def test_backend_writer_attribute_error_fails_the_stamp(app_layout, monkeypatch):
    app, package_json = _npm_app(app_layout)

    def broken_writer(self, *args):
        raise AttributeError("bug inside the writer")

    monkeypatch.setattr(
        VersionControlStamper, "_write_version_to_structured", broken_writer
    )

    err, _, _ = _stamp_app(app, "patch")

    assert err != 0
    assert f"{app}_0.0.2" not in _tags(app_layout)
    assert _status(app_layout) == ""


def test_outgoing_changes_after_push_are_not_waited_on(monkeypatch):
    sleeps = []

    class Backend:
        def push(self, tags):
            pass

        def check_for_outgoing_changes(self):
            return "still outgoing"

    monkeypatch.setattr(time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError):
        publisher._push_published_refs(Backend(), ["t"])
    assert sleeps == []


def test_failed_push_reverts_the_stamp(app_layout, monkeypatch):
    app = app_layout.app_name
    _run_vmn_init()
    _init_app(app)
    head = _git(app_layout, "rev-parse", "HEAD")
    monkeypatch.setattr(GitBackend, "push", _boom)

    err, _, _ = _stamp_app(app, "patch")

    assert err != 0
    assert _git(app_layout, "rev-parse", "HEAD") == head
    assert f"{app}_0.0.1" not in _tags(app_layout)
    assert _status(app_layout) == ""


def _vcs(app):
    reset_logger()
    _, vmn_ctx = vmn_run(["show", app])
    return vmn_ctx.vcs


def test_missing_tag_version_info_is_treated_as_absent(app_layout):
    app = app_layout.app_name
    _run_vmn_init()
    _init_app(app)
    assert _stamp_app(app, "patch", prerelease="rc")[0] == 0

    vcs = _vcs(app)
    vcs.backend.get_tag_version_info = lambda tag: (tag, None)
    vcs.release_mode = None
    assert vcs.stamp_app_version("0.0.1-rc.1") == "0.0.1-rc.2"

    tagged = []
    vcs.backend.tag = lambda tags, msgs, **kw: tagged.extend(tags)
    vcs.params.update(
        buildmetadata="b1", version_metadata_url=None, version_metadata_path=None
    )
    ver_info = vcs.ver_infos_from_repo[vcs.selected_tag]["ver_info"]
    assert vcs.add_metadata_to_version(vcs.selected_tag, ver_info) == "0.0.1-rc.1+b1"
    assert tagged == [f"{app}_0.0.1-rc.1+b1"]
