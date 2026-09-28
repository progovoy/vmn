"""`vmn show --dev`, the dev version string format and `create_snapshots`."""
import os

import yaml

from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger
from helpers import DEV_VERSION_RE, _init_app, _run_vmn_init, _show, _stamp_app


def test_show_dev(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Clean state: --dev should show plain version
    capfd.readouterr()
    err = _show(app_layout.app_name, dev=True)
    assert err == 0
    captured = capfd.readouterr()
    assert captured.out.strip() == "0.0.1"

    # Create dirty state: commit+push first (version_not_matched), then modify tracked file
    app_layout.write_file_commit_and_push("test_repo_0", "dirty.txt", "initial")
    app_layout.write_file_commit_and_push(
        "test_repo_0", "dirty.txt", "dirty content", commit=False
    )

    # --dev with dirty state: should show dev version
    capfd.readouterr()
    err = _show(app_layout.app_name, dev=True)
    assert err == 0
    captured = capfd.readouterr()
    dev_ver = captured.out.strip()
    assert DEV_VERSION_RE.match(dev_ver), f"Expected dev version format, got: {dev_ver}"
    assert dev_ver.startswith("0.0.1-dev.")

    # --dev verbose: should have dev_version key
    capfd.readouterr()
    err = _show(app_layout.app_name, dev=True, verbose=True)
    assert err == 0
    captured = capfd.readouterr()
    out_dict = yaml.safe_load(captured.out)
    assert "dev_version" in out_dict
    assert DEV_VERSION_RE.match(out_dict["dev_version"])

    # Without --dev: should show dirty dict but no dev version
    capfd.readouterr()
    err = _show(app_layout.app_name, verbose=True)
    assert err == 0
    captured = capfd.readouterr()
    out_dict = yaml.safe_load(captured.out)
    assert "dirty" in out_dict
    assert "dev_version" not in out_dict


def test_show_dev_outgoing(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Create outgoing (unpushed) commit
    app_layout.write_file_commit_and_push(
        "test_repo_0", "outgoing.txt", "unpushed", push=False
    )

    capfd.readouterr()
    err = _show(app_layout.app_name, dev=True)
    assert err == 0
    captured = capfd.readouterr()
    dev_ver = captured.out.strip()
    assert DEV_VERSION_RE.match(dev_ver), f"Expected dev version format, got: {dev_ver}"
    assert dev_ver.startswith("0.0.1-dev.")


def test_show_dev_from_file_error(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    capfd.readouterr()
    reset_logger()
    ret = vmn_run(["show", "--dev", "--from-file", app_layout.app_name])[0]
    assert ret == 1
    captured = capfd.readouterr()
    assert "--dev cannot be used with --from-file" in captured.err


def test_show_from_file_with_snapshots(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "create_snapshots": True,
        "deps": {
            "../": {
                "test_repo_0": {
                    "vcs_type": app_layout.be_type,
                    "remote": app_layout._app_backend.be.remote(),
                }
            }
        },
        "extra_info": False,
    }
    app_layout.write_conf(params["app_conf_path"], **conf)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Verify snapshots dir was created
    snap_dir = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "snapshots"
    )
    assert os.path.isdir(snap_dir)

    # show --from-file should work
    capfd.readouterr()
    err = _show(app_layout.app_name, from_file=True)
    assert err == 0
    captured = capfd.readouterr()
    assert "0.0.1" in captured.out


def test_dev_version_parsing():
    from version_stamp.core.version_math import (
        deserialize_vmn_version,
        serialize_vmn_version,
    )

    # Basic dev version
    props = deserialize_vmn_version("1.2.3-dev.abc135f.d4e5f6a")
    assert props.major == 1
    assert props.minor == 2
    assert props.patch == 3
    assert props.dev_commit == "abc135f"
    assert props.dev_diff_hash == "d4e5f6a"
    assert "dev" in props.types

    # Prerelease + dev
    props2 = deserialize_vmn_version("1.2.3-rc.1-dev.abc135f.d4e5f6a")
    assert props2.prerelease == "rc"
    assert props2.rcn == 1
    assert props2.dev_commit == "abc135f"
    assert props2.dev_diff_hash == "d4e5f6a"
    assert "dev" in props2.types
    assert "prerelease" in props2.types

    # Dev + buildmetadata
    props3 = deserialize_vmn_version("1.2.3-dev.abc135f.d4e5f6a+build.42")
    assert props3.dev_commit == "abc135f"
    assert props3.buildmetadata == "build.42"
    assert "dev" in props3.types
    assert "buildmetadata" in props3.types

    # Serialize with dev
    ver = serialize_vmn_version(
        "1.2.3",
        dev_commit="abc135f",
        dev_diff_hash="d4e5f6a",
        hide_zero_hotfix=True,
    )
    assert ver == "1.2.3-dev.abc135f.d4e5f6a"

    # Round-trip
    props_rt = deserialize_vmn_version(ver)
    assert props_rt.dev_commit == "abc135f"
    assert props_rt.dev_diff_hash == "d4e5f6a"
    assert props_rt.major == 1
    assert props_rt.minor == 2
    assert props_rt.patch == 3

    # Plain version has no dev fields
    plain = deserialize_vmn_version("1.2.3")
    assert plain.dev_commit is None
    assert plain.dev_diff_hash is None
    assert "dev" not in plain.types
