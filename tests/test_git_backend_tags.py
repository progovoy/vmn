"""GitBackend tag lookups: consistent return types and root-app tag names."""
import os
import subprocess

from helpers import _init_app, _run_vmn_init, _stamp_app
from island_helpers import _out
from version_stamp.backends.git import GitBackend


def _stamped_backend(app_layout, app_name):
    _run_vmn_init()
    _init_app(app_name)
    assert _stamp_app(app_name, "patch")[0] == 0
    return GitBackend(app_layout.repo_path)


def test_brother_tags_of_missing_tag_is_empty_dict(app_layout):
    backend = _stamped_backend(app_layout, app_layout.app_name)

    assert backend.get_all_brother_tags("no_such_app_9.9.9") == {}


def test_tag_version_info_of_non_vmn_tag_on_vmn_commit_is_empty_dict(app_layout):
    backend = _stamped_backend(app_layout, app_layout.app_name)
    _out(app_layout.repo_path, "tag", "-a", "other_9.9.9", "-m", "not vmn")

    assert backend.get_tag_version_info("other_9.9.9") == ("other_9.9.9", {})


def _recommit_head_without_tags(repo_path):
    env = dict(os.environ, GIT_COMMITTER_DATE="2001-01-01T00:00:00")
    subprocess.run(
        ["git", "-C", repo_path, "commit", "-q", "--amend", "--no-edit"],
        check=True,
        env=env,
    )
    return _out(repo_path, "rev-parse", "HEAD")


def test_rebased_root_app_commit_recovers_its_tags(app_layout):
    app_name = "root_app/service1"
    backend = _stamped_backend(app_layout, app_name)
    new_hex = _recommit_head_without_tags(app_layout.repo_path)

    ver_infos = backend.get_all_commit_tags_log_impl(new_hex, [], app_name)

    assert "root_app-service1_0.0.1" in ver_infos
    assert "root_app_1" in ver_infos


def test_tag_message_with_leading_comment_parses_like_plain_yaml(app_layout):
    backend = _stamped_backend(app_layout, app_layout.app_name)
    tag_name = f"{app_layout.app_name}_0.0.1"
    message = _out(app_layout.repo_path, "tag", "-l", "--format=%(contents)", tag_name)
    prefixed = f"{app_layout.app_name}_9.9.9"
    _out(
        app_layout.repo_path,
        "tag", "-a", prefixed, tag_name, "-m", f"# leading note\n---\n{message}",
    )

    _, plain = backend.parse_tag_message(tag_name)
    _, with_prefix = backend.parse_tag_message(prefixed)

    assert with_prefix["ver_info"] is not None
    assert with_prefix["ver_info"] == plain["ver_info"]


def _count_grep_logs(backend, monkeypatch):
    calls = []

    def counting_log(git_cmd, *args, **kwargs):
        if any(str(a).startswith("--grep=") for a in args):
            calls.append(args)
        return git_cmd._call_process("log", *args, **kwargs)

    monkeypatch.setattr(type(backend._be.git), "log", counting_log, raising=False)
    return calls


def test_walk_back_past_untagged_stamp_commits_streams_one_git_log(
    app_layout, monkeypatch
):
    app_name = app_layout.app_name
    backend = _stamped_backend(app_layout, app_name)
    for version in ("0.0.2", "0.0.3"):
        app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", version)
        assert _stamp_app(app_name, "patch")[0] == 0
        _out(app_layout.repo_path, "tag", "-d", f"{app_name}_{version}")
    calls = _count_grep_logs(backend, monkeypatch)

    tag_names, cobj, ver_infos = backend.get_latest_stamp_tags(app_name, False)

    assert tag_names == [f"{app_name}_0.0.1"]
    assert cobj.hexsha == _out(
        app_layout.repo_path, "rev-list", "-n1", f"{app_name}_0.0.1"
    )
    # the top stamp commit, then one streamed walk back from its parent
    assert len(calls) == 2
