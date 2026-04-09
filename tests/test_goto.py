import shutil

import yaml

from helpers import (
    _configure_2_deps,
    _goto,
    _init_app,
    _release_app,
    _run_vmn_init,
    _show,
    _stamp_app,
)


def test_basic_goto(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.1"

    c1 = app_layout._app_backend.be.changeset()
    err = _goto(app_layout.app_name, version="0.0.2")
    assert err == 1

    err = _goto(app_layout.app_name, version="1.3.0")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    captured = capfd.readouterr()
    assert (
        "[INFO] Found existing version 1.3.0 and nothing has changed. Will not stamp\n"
        == captured.out
    )

    c2 = app_layout._app_backend.be.changeset()
    assert c1 != c2
    err = _goto(app_layout.app_name, version="1.3.1")
    assert err == 0
    c3 = app_layout._app_backend.be.changeset()
    assert c1 == c3

    err = _goto(app_layout.app_name)
    assert err == 0

    c4 = app_layout._app_backend.be.changeset()
    assert c1 == c4

    root_app_name = "some_root_app/service1"
    _init_app(root_app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    rc1 = app_layout._app_backend.be.changeset()

    app_layout.write_file_commit_and_push("test_repo_0", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    rc2 = app_layout._app_backend.be.changeset()

    assert rc1 != rc2

    err = _goto(root_app_name, version="1.3.0")
    assert err == 0

    assert rc1 == app_layout._app_backend.be.changeset()

    err = _goto(root_app_name)
    assert err == 0

    assert rc2 == app_layout._app_backend.be.changeset()

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    assert rc2 == app_layout._app_backend.be.changeset()

    app_layout.write_file_commit_and_push("test_repo_0", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.5.0"

    rc3 = app_layout._app_backend.be.changeset()

    root_name = root_app_name.split("/")[0]

    err = _goto(root_name, version="1", root=True)
    assert err == 0

    assert rc1 == app_layout._app_backend.be.changeset()

    err = _goto(root_name, root=True)
    assert err == 0

    assert rc3 == app_layout._app_backend.be.changeset()

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    deps = ver_info["stamping"]["app"]["changesets"]

    err = _goto(
        root_app_name,
        version=f"1.5.0+{deps['.']['hash']}",
    )
    assert err == 0

    err = _goto(
        root_app_name,
        version=f"1.5.0+{deps['.']['hash'][:-10]}",
    )
    assert err == 0

    capfd.readouterr()

    err = _goto(
        root_app_name,
        version=f"1.5.0+{deps['.']['hash'][:-10]}X",
    )
    assert err == 1

    captured = capfd.readouterr()
    assert "[ERROR] Wrong unique id\n" == captured.err


def test_goto_print(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")

    app_layout.write_file_commit_and_push("test_repo_0", "my.js", "some text")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="major")

    capfd.readouterr()

    err = _goto(app_layout.app_name, version="1.3.0")
    assert err == 0

    sout, serr = capfd.readouterr()
    assert f"[INFO] You are at version 1.3.0 of {app_layout.app_name}\n" == sout

    err = _goto(app_layout.app_name)
    assert err == 0

    sout, serr = capfd.readouterr()
    assert (
        f"[INFO] You are at the tip of the branch of version 2.0.0 for {app_layout.app_name}\n"
        == sout
    )


def test_goto_deleted_repos(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _configure_2_deps(app_layout, params)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    dir_path = app_layout._repos["repo2"]["path"]
    # deleting repo_b
    shutil.rmtree(dir_path)

    err = _goto(app_layout.app_name, version="0.0.2")
    assert err == 0


def test_rc_goto(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    try:
        err, ver_info, _ = _stamp_app(
            app_layout.app_name, release_mode="minor", prerelease="rc_aaa"
        )
        assert err == 0
    except AssertionError:
        pass

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rcaaa"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rcaaa.1"

    err = _goto(app_layout.app_name, version="1.3.0-rcaaa.1")
    assert err == 0


def test_dirty_no_ff_rebase(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "minor")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    main_branch = app_layout._app_backend.be.get_active_branch()
    other_branch = "topic"

    app_layout.checkout(other_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg1")
    _stamp_app(app_layout.app_name, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg2")
    _stamp_app(app_layout.app_name, "patch")

    app_layout.rebase(main_branch, other_branch, no_ff=True)

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    res = yaml.safe_load(captured.out)
    assert "0.1.2" == res["out"]
    assert len(res["dirty"]) == 2
    assert "version_not_matched" in res["dirty"]
    assert "outgoing" in res["dirty"]
