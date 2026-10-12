"""Deprecated release-mode conf keys: silent on read, rewritten by stamp."""
import os
import subprocess

from helpers import _init_app, _run_vmn_init, _show, _stamp_app
from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger


def _stamped(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    return params["app_conf_path"]


def _commit_conf(app_layout, conf_path, text):
    with open(conf_path, "w") as f:
        f.write(text)
    app_layout.git_cmd(args=["add", conf_path])
    app_layout.git_cmd(args=["commit", "-m", "update conf"])
    app_layout.git_cmd(args=["push"])


def _read(path):
    with open(path) as f:
        return f.read()


def _committed(app_layout, path):
    rel = os.path.relpath(path, app_layout.repo_path)
    return subprocess.check_output(
        ["git", "show", f"HEAD:{rel}"], cwd=app_layout.repo_path, text=True
    )


def _change(app_layout, msg="fix: something"):
    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", msg, commit_msg=msg)


TOP_LEVEL = """\
# my comment
conf:
  conventional_commits: true
  # policy comment
  default_release_mode: strict  # trailing
"""


def test_read_command_does_not_warn_about_deprecated_keys(app_layout, capfd):
    conf_path = _stamped(app_layout)
    _commit_conf(app_layout, conf_path, TOP_LEVEL)

    capfd.readouterr()
    assert _show(app_layout.app_name) == 0

    out, err = capfd.readouterr()
    assert "Migrating" not in out + err
    assert "WARNING" not in out + err
    assert _read(conf_path) == TOP_LEVEL


def test_stamp_rewrites_top_level_policy_keeping_comments(app_layout, capfd):
    conf_path = _stamped(app_layout)
    _commit_conf(app_layout, conf_path, TOP_LEVEL)
    _change(app_layout)

    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name)
    out, serr = capfd.readouterr()

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    expected = TOP_LEVEL.replace(
        "default_release_mode: strict", "release_mode_policy: strict"
    )
    assert _read(conf_path) == expected
    assert _committed(app_layout, conf_path) == expected
    assert f"Migrated deprecated keys in {conf_path}" in out
    assert "WARNING" not in out + serr


def test_migrated_policy_keeps_working_on_next_stamp(app_layout):
    conf_path = _stamped(app_layout)
    _commit_conf(app_layout, conf_path, TOP_LEVEL)
    _change(app_layout)
    assert _stamp_app(app_layout.app_name)[0] == 0

    _change(app_layout, "feat: more")
    err, ver_info, _ = _stamp_app(app_layout.app_name)

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.1.0"


def test_stamp_drops_deprecated_line_when_policy_exists(app_layout):
    conf_path = _stamped(app_layout)
    _commit_conf(
        app_layout,
        conf_path,
        "conf:\n"
        "  conventional_commits: true\n"
        "  release_mode_policy: strict\n"
        "  default_release_mode: optional\n",
    )
    _change(app_layout)

    assert _stamp_app(app_layout.app_name)[0] == 0

    assert _read(conf_path) == (
        "conf:\n  conventional_commits: true\n  release_mode_policy: strict\n"
    )


def test_stamp_rewrites_nested_form(app_layout):
    conf_path = _stamped(app_layout)
    _commit_conf(
        app_layout,
        conf_path,
        "conf:\n"
        "  conventional_commits:\n"
        "    default_release_mode: strict\n"
        "  template: '[{major}][.{minor}][.{patch}]'\n",
    )
    _change(app_layout)

    err, ver_info, _ = _stamp_app(app_layout.app_name)

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    assert _read(conf_path) == (
        "conf:\n"
        "  conventional_commits: true\n"
        "  release_mode_policy: strict\n"
        "  template: '[{major}][.{minor}][.{patch}]'\n"
    )


def test_stamp_leaves_real_default_release_mode_alone(app_layout, capfd):
    conf_path = _stamped(app_layout)
    text = (
        "conf:\n"
        "  conventional_commits: true\n"
        "  release_mode_policy: optional\n"
        "  default_release_mode: minor\n"
    )
    _commit_conf(app_layout, conf_path, text)
    _change(app_layout, "no conventional format here")

    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name)
    out, _ = capfd.readouterr()

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.1.0"
    assert _read(conf_path) == text
    assert "Migrated" not in out


def test_dry_run_reports_but_leaves_conf(app_layout, capfd):
    conf_path = _stamped(app_layout)
    _commit_conf(app_layout, conf_path, TOP_LEVEL)
    _change(app_layout)

    capfd.readouterr()
    reset_logger()
    err, _ = vmn_run(["stamp", "--dry-run", app_layout.app_name])
    out, _ = capfd.readouterr()

    assert err == 0
    assert _read(conf_path) == TOP_LEVEL
    assert f"Would migrate deprecated keys in {conf_path}" in out


def _rewritten(tmp_path, text, dry_run=False):
    from version_stamp.compat.conf_rewrite import rewrite_deprecated_conf_keys

    path = tmp_path / "conf.yml"
    path.write_text(text)
    changed = rewrite_deprecated_conf_keys(str(path), dry_run=dry_run)
    return changed, path.read_text()


def test_rewrite_flow_style_nested_policy(tmp_path):
    changed, text = _rewritten(
        tmp_path,
        "conf:\n"
        "  conventional_commits: {default_release_mode: strict}  # cc\n"
        "  template: '[{major}][.{minor}][.{patch}]'\n",
    )

    assert changed
    assert text == (
        "conf:\n"
        "  conventional_commits: true  # cc\n"
        "  release_mode_policy: strict\n"
        "  template: '[{major}][.{minor}][.{patch}]'\n"
    )


def test_rewrite_flow_style_nested_policy_keeps_other_keys(tmp_path):
    _, text = _rewritten(
        tmp_path,
        "conf:\n  conventional_commits: {default_release_mode: 'optional', foo: bar}\n",
    )

    assert text == (
        "conf:\n"
        "  conventional_commits: {foo: bar}\n"
        "  release_mode_policy: optional\n"
    )


def test_rewrite_flow_style_drops_key_when_policy_exists(tmp_path):
    _, text = _rewritten(
        tmp_path,
        "conf:\n"
        "  release_mode_policy: optional\n"
        "  conventional_commits: {default_release_mode: strict}\n",
    )

    assert text == (
        "conf:\n  release_mode_policy: optional\n  conventional_commits: true\n"
    )


def test_rewrite_removes_vmn_version_file_block(tmp_path):
    _, text = _rewritten(
        tmp_path,
        "conf:\n"
        "  version_backends:\n"
        "    # backends comment\n"
        "    vmn_version_file:\n"
        "      path: version.txt\n"
        "    npm:\n"
        "      path: package.json  # npm\n"
        "  template: '[{major}]'\n",
    )

    assert text == (
        "conf:\n"
        "  version_backends:\n"
        "    # backends comment\n"
        "    npm:\n"
        "      path: package.json  # npm\n"
        "  template: '[{major}]'\n"
    )


def test_rewrite_removes_flow_style_vmn_version_file(tmp_path):
    _, text = _rewritten(
        tmp_path,
        "conf:\n"
        "  version_backends: {vmn_version_file: {path: v.txt}, npm: {path: package.json}}\n",
    )

    assert text == "conf:\n  version_backends: {npm: {path: package.json}}\n"


def test_rewrite_removes_emptied_version_backends(tmp_path):
    _, block = _rewritten(
        tmp_path,
        "conf:\n  version_backends:\n    vmn_version_file: {}\n  template: '[{major}]'\n",
    )
    _, flow = _rewritten(
        tmp_path,
        "conf:\n  version_backends: {vmn_version_file: {}}  # old\n  template: '[{major}]'\n",
    )

    assert block == "conf:\n  template: '[{major}]'\n"
    assert flow == "conf:\n  template: '[{major}]'\n"


def test_rewrite_keeps_an_emptied_conf_a_mapping(tmp_path):
    _, text = _rewritten(
        tmp_path, "conf:\n  # only backend\n  version_backends:\n    vmn_version_file: {}\n"
    )

    assert text == "conf: {}\n  # only backend\n"


def test_rewrite_dry_run_reports_vmn_version_file_without_writing(tmp_path):
    original = "conf:\n  version_backends:\n    vmn_version_file: {}\n"

    changed, text = _rewritten(tmp_path, original, dry_run=True)

    assert changed
    assert text == original


VMN_VERSION_FILE_CONF = """\
conf:
  # keep me
  template: '[{major}][.{minor}][.{patch}]'
  version_backends:
    vmn_version_file:
      path: version.txt
"""
VMN_VERSION_FILE_MIGRATED = """\
conf:
  # keep me
  template: '[{major}][.{minor}][.{patch}]'
"""


def test_stamp_drops_vmn_version_file_without_warning(app_layout, capfd):
    conf_path = _stamped(app_layout)
    _commit_conf(app_layout, conf_path, VMN_VERSION_FILE_CONF)
    _change(app_layout)

    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    out, serr = capfd.readouterr()

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    assert _read(conf_path) == VMN_VERSION_FILE_MIGRATED
    assert _committed(app_layout, conf_path) == VMN_VERSION_FILE_MIGRATED
    assert out.count(f"Migrated deprecated keys in {conf_path}") == 1
    assert "WARNING" not in out + serr


def test_dry_run_with_vmn_version_file_leaves_conf_without_warning(app_layout, capfd):
    conf_path = _stamped(app_layout)
    _commit_conf(app_layout, conf_path, VMN_VERSION_FILE_CONF)
    _change(app_layout)

    capfd.readouterr()
    reset_logger()
    err, _ = vmn_run(["stamp", "--dry-run", "-r", "patch", app_layout.app_name])
    out, serr = capfd.readouterr()

    assert err == 0
    assert _read(conf_path) == VMN_VERSION_FILE_CONF
    assert f"Would migrate deprecated keys in {conf_path}" in out
    assert "WARNING" not in out + serr
