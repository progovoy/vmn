import yaml

from helpers import _init_app, _release_app, _run_vmn_init, _show, _stamp_app


def test_rc_stamping(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc.2"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="beta")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-beta.1"
    assert data["prerelease"] == "beta"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-beta.2"
    assert data["prerelease"] == "beta"

    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-beta.2")
    capfd.readouterr()

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"
    assert data["prerelease"] == "release"

    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0")

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"
    assert data["prerelease"] == "release"

    tags_before = app_layout.get_all_tags()
    for t in tags_before:
        app_layout._app_backend.be._be.delete_tag(t)

    app_layout._app_backend.be._be.git.fetch("--tags")
    tags_after = app_layout.get_all_tags()

    assert tags_before == tags_after

    for item in ["2.0.0", "3.0.0"]:
        app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
        err, ver_info, _ = _stamp_app(
            app_layout.app_name, release_mode="major", prerelease="rc"
        )
        assert err == 0

        assert "vmn_info" in ver_info
        data = ver_info["stamping"]["app"]
        assert data["_version"] == f"{item}-rc.1"
        assert data["prerelease"] == "rc"

        _, ver_info, _ = _release_app(app_layout.app_name, f"{item}-rc.1")

        assert "vmn_info" in ver_info
        data = ver_info["stamping"]["app"]
        assert data["_version"] == item
        assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.1.0"
    assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.2.0-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.3.0-rc.1"
    assert data["prerelease"] == "rc"

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.3.0-rc.1"


def test_multi_prereleases(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, starting_version="2.13.3")

    app_layout._app_backend.be.get_active_branch()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="564"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="564"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="564"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="513"
    )

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="508"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="508"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="staging"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="513"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="staging"
    )

    capfd.readouterr()
    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)

    assert "2.13.4-staging.2" == tmp["version"]

    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert "2.13.4-staging.2" == tmp["version"]


def test_orm_rc_from_release(app_layout, capfd):
    # Prepare
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    # Actual Test
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"


def test_orm_rc_from_release_globally_latest_other_rc(app_layout, capfd):
    # Prepare
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc1"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc1.1"
    assert data["prerelease"] == "rc1"

    # Actual Test
    app_layout.checkout(main_branch)
    app_layout.checkout("second_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc2"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc2.1"
    assert data["prerelease"] == "rc2"


def test_orm_rc_from_release_globally_latest_same_rc(app_layout, capfd):
    # Prepare
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    # Actual Test
    app_layout.checkout(main_branch)
    app_layout.checkout("second_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.2"
    assert data["prerelease"] == "rc"


def test_orm_rc_from_rc_globally_latest_release(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    main_branch = app_layout._app_backend.be.get_active_branch()

    first_branch = "first_branch"
    second_branch = "second_branch"

    branches = [first_branch, second_branch]
    for i in range(len(branches)):
        app_layout.checkout(branches[i], create_new=True)
        app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

        err, ver_info, _ = _stamp_app(
            app_layout.app_name,
            optional_release_mode="patch",
            prerelease=f"rc{i}",
        )
        assert err == 0

        data = ver_info["stamping"]["app"]
        assert data["_version"] == f"0.0.2-rc{i}.1"
        assert data["prerelease"] == f"rc{i}"

        app_layout.checkout(main_branch)

    err, ver_info, _ = _release_app(app_layout.app_name, "0.0.2-rc0.1")

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2"

    # Actual Test
    app_layout.checkout(second_branch)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 1


def test_orm_rc_from_rc_globally_latest_other_rc(app_layout, capfd):
    # Prepare
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc1"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc1.1"
    assert data["prerelease"] == "rc1"

    # Actual Test
    app_layout.checkout("second_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc2"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc2.1"
    assert data["prerelease"] == "rc2"


def test_orm_rc_from_rc_globally_latest_same_rc(app_layout, capfd):
    # Prepare
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    # Actual Test
    app_layout.checkout("second_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.2"
    assert data["prerelease"] == "rc"


def test_orm_rc_ending_with_dot(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc."
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"


def test_pr_rc_ending_with_dot(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc."
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc.")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.2"
    assert data["prerelease"] == "rc"


def test_orm_rc_with_strange_name_dot(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc.1"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1.1"
    assert data["prerelease"] == "rc.1"


def test_orm_rc_with_strange_name_hyphen(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc-1"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc-1.1"
    assert data["prerelease"] == "rc-1"


def test_orm_rc_with_strange_name_underscore(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc_1"
    )
    assert err == 1
