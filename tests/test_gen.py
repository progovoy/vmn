import os

import yaml

from helpers import (
    _configure_2_deps,
    _gen,
    _goto,
    _init_app,
    _run_vmn_init,
    _stamp_app,
)


def test_jinja2_gen(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    jinja2_content = (
        "VERSION: {{version}}\n"
        "NAME: {{name}}\n"
        "BRANCH: {{stamped_on_branch}}\n"
        "RELEASE_MODE: {{release_mode}}\n"
        "{% for k,v in changesets.items() %}\n"
        "{{k}}:\n"
        "  hash: {{v.hash}}\n"
        "  remote: {{v.remote}}\n"
        "  vcs_type: {{v.vcs_type}}\n"
        "  state: {{v.state}}\n"
        "{% endfor %}\n"
    )
    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.jinja2", jinja2_content, commit=False
    )

    tpath = os.path.join(app_layout._repos["test_repo_0"]["path"], "f1.jinja2")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "jinja_out.txt")
    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    m_time = os.path.getmtime(opath)

    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    m_time_after = os.path.getmtime(opath)

    assert m_time == m_time_after

    # read to clear stderr and out
    capfd.readouterr()

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True)
    assert err == 1

    captured = capfd.readouterr()

    assert (
        "[ERROR] The repository and maybe"
        " some of its dependencies are in dirty state.Dirty states"
        " found: {'version_not_matched'}" in captured.err
    )

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    capfd.readouterr()

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True, version="0.0.1")
    assert err == 1

    captured = capfd.readouterr()

    assert (
        "[ERROR] The repository is not exactly at "
        "version: 0.0.1. You can use `vmn goto` in order "
        "to jump to that version.\nRefusing to gen." in captured.err
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    err = _goto(app_layout.app_name, version="0.0.1")
    assert err == 0

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True)
    assert err == 0

    err = _goto(app_layout.app_name)
    assert err == 0

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True)
    assert err == 1

    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    new_name = f"{app_layout.app_name}2/s1"
    _init_app(new_name)

    err, _, _ = _stamp_app(new_name, "patch")
    assert err == 0

    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _configure_2_deps(app_layout, params)
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg2", commit=False)
    app_layout.write_file_commit_and_push("repo2", "f1.file", "msg1", push=False)

    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["VERSION"] == "0.0.3"
        assert data["RELEASE_MODE"] == "patch"
        assert "dirty_deps" in data["."]["state"]
        assert "version_not_matched" in data["."]["state"]
        assert "pending" in data[os.path.join("..", "repo1")]["state"]
        assert "outgoing" in data[os.path.join("..", "repo2")]["state"]


def test_jinja2_gen_custom(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    jinja2_content = "VERSION: {{version}}\n" "Custom: {{k1}}\n"
    app_layout.write_file_commit_and_push("test_repo_0", "f1.jinja2", jinja2_content)

    custom_keys_content = "k1: 5\n"
    app_layout.write_file_commit_and_push(
        "test_repo_0", "custom.yml", custom_keys_content
    )

    tpath = os.path.join(app_layout._repos["test_repo_0"]["path"], "f1.jinja2")
    custom_path = os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "jinja_out.txt")
    err = _gen(app_layout.app_name, tpath, opath, custom_path=custom_path)
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["VERSION"] == "0.0.1"
        assert data["Custom"] == 5


def test_jinja2_gen_rn_simple(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()
    commit_msg = """fix: prevent racing of requests"""

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "content", commit_msg=commit_msg
    )

    jinja2_content = "{{release_notes}}\n"
    app_layout.write_file_commit_and_push("test_repo_0", "f1.jinja2", jinja2_content)

    tpath = os.path.join(app_layout._repos["test_repo_0"]["path"], "f1.jinja2")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "jinja_out.txt")
    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    with open(opath, "r") as f:
        assert "prevent racing of requests" in f.read().lower()


def test_jinja2_gen_rn_custom_file(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    commit_msg = """fix: prevent racing of requests"""

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "content", commit_msg=commit_msg
    )

    jinja2_content = "VERSION: {{version}}\n" "Release Notes: {{release_notes}}\n"
    app_layout.write_file_commit_and_push("test_repo_0", "f1.jinja2", jinja2_content)

    custom_keys_content = "release_notes_conf_path: cliffconf.toml\n"
    app_layout.write_file_commit_and_push(
        "test_repo_0", "custom.yml", custom_keys_content
    )

    tpath = os.path.join(app_layout._repos["test_repo_0"]["path"], "f1.jinja2")
    custom_path = os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "jinja_out.txt")
    err = _gen(app_layout.app_name, tpath, opath, custom_path=custom_path)
    assert err == 0

    with open(opath, "r") as f:
        assert "prevent racing of requests" in f.read().lower()
