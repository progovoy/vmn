import os
import re
import subprocess
import tarfile
from unittest.mock import patch as mock_patch

import boto3
import pytest
import yaml
from moto import mock_aws

from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger
from test_ver_stamp import (
    _init_app,
    _goto,
    _run_vmn_init,
    _show,
    _snapshot,
    _stamp_app,
)


_DEV_VERSION_RE = re.compile(r"^.+-dev\.[0-9a-f]{7}\.[0-9a-f]{7}$")


def _extract_dev_verstr(output):
    """Extract a dev version string from output that may contain [INFO] lines."""
    for line in output.strip().split("\n"):
        line = line.strip()
        if line.startswith("["):
            continue
        if _DEV_VERSION_RE.match(line):
            return line
    return None


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
    assert _DEV_VERSION_RE.match(dev_ver), f"Expected dev version format, got: {dev_ver}"
    assert dev_ver.startswith("0.0.1-dev.")

    # --dev verbose: should have dev_version key
    capfd.readouterr()
    err = _show(app_layout.app_name, dev=True, verbose=True)
    assert err == 0
    captured = capfd.readouterr()
    out_dict = yaml.safe_load(captured.out)
    assert "dev_version" in out_dict
    assert _DEV_VERSION_RE.match(out_dict["dev_version"])

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
    assert _DEV_VERSION_RE.match(dev_ver), f"Expected dev version format, got: {dev_ver}"
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


def test_snapshot_create_and_list(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Snapshot with clean state: returns 0 (no changes to snapshot)
    capfd.readouterr()
    err = _snapshot(app_layout.app_name)
    assert err == 0

    # Create dirty state: push a commit first, then modify tracked file
    app_layout.write_file_commit_and_push("test_repo_0", "snap_file.txt", "initial")
    app_layout.write_file_commit_and_push(
        "test_repo_0", "snap_file.txt", "snapshot content", commit=False
    )

    # Create snapshot with note
    capfd.readouterr()
    err = _snapshot(app_layout.app_name, note="test note")
    assert err == 0
    captured = capfd.readouterr()
    verstr = _extract_dev_verstr(captured.out)
    assert verstr is not None, f"No dev version found in output: {captured.out}"
    assert verstr.startswith("0.0.1-dev.")

    # List snapshots
    capfd.readouterr()
    err = _snapshot(app_layout.app_name, action="list")
    assert err == 0
    captured = capfd.readouterr()
    assert verstr in captured.out
    assert "test note" in captured.out

    # Show snapshot
    capfd.readouterr()
    err = _snapshot(app_layout.app_name, action="show", version=verstr)
    assert err == 0
    captured = capfd.readouterr()
    assert "base_version" in captured.out
    assert "working_tree" in captured.out.lower() or "patch" in captured.out.lower()


def test_snapshot_note_update(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "note_file.txt", "initial")
    app_layout.write_file_commit_and_push(
        "test_repo_0", "note_file.txt", "content", commit=False
    )

    capfd.readouterr()
    err = _snapshot(app_layout.app_name, note="original note")
    assert err == 0
    verstr = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    # Update note
    err = _snapshot(app_layout.app_name, action="note", version=verstr, note="updated note")
    assert err == 0

    # Verify updated note
    capfd.readouterr()
    err = _snapshot(app_layout.app_name, action="show", version=verstr)
    assert err == 0
    captured = capfd.readouterr()
    assert "updated note" in captured.out


def test_snapshot_content_addressable(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "addr.txt", "initial")
    app_layout.write_file_commit_and_push(
        "test_repo_0", "addr.txt", "deterministic content", commit=False
    )

    # First snapshot
    capfd.readouterr()
    err = _snapshot(app_layout.app_name)
    assert err == 0
    verstr1 = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr1 is not None

    # Second snapshot of same state
    capfd.readouterr()
    err = _snapshot(app_layout.app_name)
    assert err == 0
    verstr2 = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr2 is not None

    assert verstr1 == verstr2


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
        "1.2.3", dev_commit="abc135f", dev_diff_hash="d4e5f6a",
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


def test_goto_dev_version(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Create dirty state: push a commit first, then modify tracked file
    app_layout.write_file_commit_and_push("test_repo_0", "goto_test.txt", "initial")
    test_file = os.path.join(app_layout.repo_path, "goto_test.txt")
    with open(test_file, "w") as f:
        f.write("goto content")

    # Create snapshot
    capfd.readouterr()
    err = _snapshot(app_layout.app_name)
    assert err == 0
    verstr = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    # Discard local changes
    subprocess.run(
        ["git", "checkout", "."],
        cwd=app_layout.repo_path,
        capture_output=True,
    )
    with open(test_file) as f:
        assert f.read() == "initial"  # back to committed version

    # Goto dev version
    err = _goto(app_layout.app_name, version=verstr)
    assert err == 0

    # Verify file was restored with dirty content
    assert os.path.exists(test_file)
    with open(test_file) as f:
        assert f.read() == "goto content"


def test_snapshot_restore(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Create dirty state: push a commit first, then modify tracked file
    app_layout.write_file_commit_and_push("test_repo_0", "restore_test.txt", "initial")
    test_file = os.path.join(app_layout.repo_path, "restore_test.txt")
    with open(test_file, "w") as f:
        f.write("restore content")

    # Create snapshot
    capfd.readouterr()
    err = _snapshot(app_layout.app_name, note="test restore")
    assert err == 0
    verstr = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    # Discard local changes
    subprocess.run(
        ["git", "checkout", "."],
        cwd=app_layout.repo_path,
        capture_output=True,
    )
    with open(test_file) as f:
        assert f.read() == "initial"  # back to committed version

    # Restore via snapshot restore command
    err = _snapshot(app_layout.app_name, action="restore", version=verstr)
    assert err == 0

    # Verify file was restored with dirty content
    assert os.path.exists(test_file)
    with open(test_file) as f:
        assert f.read() == "restore content"


def test_snapshot_diff(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Create dirty state and snapshot 1
    app_layout.write_file_commit_and_push("test_repo_0", "diff_file.txt", "initial")
    app_layout.write_file_commit_and_push(
        "test_repo_0", "diff_file.txt", "change A", commit=False
    )

    capfd.readouterr()
    err = _snapshot(app_layout.app_name, note="snapshot A")
    assert err == 0
    verstr1 = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr1 is not None

    # Reset changes
    subprocess.run(
        ["git", "checkout", "."],
        cwd=app_layout.repo_path,
        check=True,
    )

    # Create different dirty state and snapshot 2
    app_layout.write_file_commit_and_push(
        "test_repo_0", "diff_file.txt", "change B", commit=False
    )

    capfd.readouterr()
    err = _snapshot(app_layout.app_name, note="snapshot B")
    assert err == 0
    verstr2 = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr2 is not None

    # Reset changes for clean diff
    subprocess.run(
        ["git", "checkout", "."],
        cwd=app_layout.repo_path,
        check=True,
    )

    # Run diff between the two snapshots
    capfd.readouterr()
    err = _snapshot(
        app_layout.app_name, action="diff", version=verstr1, to_version=verstr2
    )
    assert err == 0
    captured = capfd.readouterr()
    assert "---" in captured.out
    assert "+++" in captured.out


def test_snapshot_diff_current(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Create dirty state and snapshot
    app_layout.write_file_commit_and_push("test_repo_0", "curr_file.txt", "initial")
    app_layout.write_file_commit_and_push(
        "test_repo_0", "curr_file.txt", "snapshot content", commit=False
    )

    capfd.readouterr()
    err = _snapshot(app_layout.app_name, note="for current diff")
    assert err == 0
    verstr = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    # Now modify the file differently (still uncommitted)
    test_file = os.path.join(app_layout.repo_path, "curr_file.txt")
    with open(test_file, "w") as f:
        f.write("different content for current")

    # Run diff against current working state
    capfd.readouterr()
    err = _snapshot(
        app_layout.app_name, action="diff", version=verstr, to_version="current"
    )
    assert err == 0
    captured = capfd.readouterr()
    assert "---" in captured.out
    assert "+++" in captured.out


def test_snapshot_metadata_hooks(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Create dirty state: commit file first, then modify it
    app_layout.write_file_commit_and_push("test_repo_0", "dirty_file.txt", "initial")
    dirty_file = os.path.join(app_layout.repo_path, "dirty_file.txt")
    with open(dirty_file, "w") as f:
        f.write("dirty content")

    # Create snapshot with metadata
    capfd.readouterr()
    ret = _snapshot(
        app_layout.app_name,
        action="create",
        meta=["lr=3e-4", "epochs=100"],
    )
    assert ret == 0
    captured = capfd.readouterr()
    assert "0.0.1" in captured.out

    # Show snapshot and verify user_meta appears
    verstr = _extract_dev_verstr(captured.out)
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, action="show", version=verstr)
    assert ret == 0
    show_out = capfd.readouterr().out
    assert "lr" in show_out
    assert "3e-4" in show_out
    assert "user_meta" in show_out

    # Create a second snapshot with different metadata
    # Need different dirty content for a different hash
    with open(dirty_file, "w") as f:
        f.write("different dirty content")
    capfd.readouterr()
    ret = _snapshot(
        app_layout.app_name,
        action="create",
        meta=["lr=1e-5", "epochs=200"],
    )
    assert ret == 0

    # List with filter: should show only the first snapshot
    capfd.readouterr()
    ret = _snapshot(
        app_layout.app_name,
        action="list",
        filter_args=["lr=3e-4"],
    )
    assert ret == 0
    filtered_out = capfd.readouterr().out
    assert "lr=3e-4" in filtered_out
    assert "lr=1e-5" not in filtered_out

    # List without filter: both should appear
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, action="list")
    assert ret == 0
    all_out = capfd.readouterr().out
    assert "lr=3e-4" in all_out
    assert "lr=1e-5" in all_out


def test_snapshot_metadata_file(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Create dirty state: commit file first, then modify it
    app_layout.write_file_commit_and_push("test_repo_0", "dirty_file.txt", "initial")
    dirty_file = os.path.join(app_layout.repo_path, "dirty_file.txt")
    with open(dirty_file, "w") as f:
        f.write("dirty content")

    # Write a YAML metadata file
    meta_path = os.path.join(app_layout.repo_path, "meta.yml")
    meta_content = {
        "model": {"type": "transformer", "layers": 12},
        "dataset": "imagenet",
    }
    with open(meta_path, "w") as f:
        yaml.dump(meta_content, f)

    # Create snapshot with meta-file
    capfd.readouterr()
    ret = _snapshot(
        app_layout.app_name,
        action="create",
        meta_file=meta_path,
    )
    assert ret == 0

    # Show snapshot and verify nested structure
    verstr = _extract_dev_verstr(capfd.readouterr().out)
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, action="show", version=verstr)
    assert ret == 0
    show_out = capfd.readouterr().out
    assert "user_meta" in show_out
    assert "transformer" in show_out
    assert "layers" in show_out
    assert "imagenet" in show_out


def test_snapshot_export(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Create dirty state
    app_layout.write_file_commit_and_push("test_repo_0", "export_file.txt", "initial")
    app_layout.write_file_commit_and_push(
        "test_repo_0", "export_file.txt", "export content", commit=False
    )

    # Create snapshot
    capfd.readouterr()
    err = _snapshot(app_layout.app_name, note="export test")
    assert err == 0
    verstr = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    # Export as tarball (new behavior: materializes workdir into tarball)
    output_path = os.path.join(app_layout.repo_path, "snapshot_export.tar.gz")
    capfd.readouterr()
    err = _snapshot(
        app_layout.app_name, action="export", version=verstr, output=output_path
    )
    assert err == 0

    # Verify tarball exists and contains vmn_metadata.yml
    assert os.path.isfile(output_path)
    with tarfile.open(output_path, "r:gz") as tar:
        names = tar.getnames()
        assert any("vmn_metadata.yml" in n for n in names)


@mock_aws
def test_s3_snapshot_save():
    """Test S3 backend save — full round-trip via moto."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    from version_stamp.cli.snapshot import S3SnapshotStorage
    storage = S3SnapshotStorage("test-bucket", prefix="test-prefix")

    metadata = {"verstr": "1.0.0-dev.abc1234.def5678", "base_version": "1.0.0"}
    patches = {"working_tree": "diff --git a/f.txt b/f.txt\n+hello\n"}

    storage.save("my_app", "1.0.0-dev.abc1234.def5678", metadata, patches)

    # Verify objects were actually written
    meta_resp = s3.get_object(
        Bucket="test-bucket",
        Key="test-prefix/my_app/1.0.0-dev.abc1234.def5678/metadata.yml",
    )
    loaded = yaml.safe_load(meta_resp["Body"].read().decode("utf-8"))
    assert loaded["verstr"] == "1.0.0-dev.abc1234.def5678"

    patch_resp = s3.get_object(
        Bucket="test-bucket",
        Key="test-prefix/my_app/1.0.0-dev.abc1234.def5678/working_tree.patch",
    )
    assert b"+hello" in patch_resp["Body"].read()


@mock_aws
def test_s3_snapshot_load():
    """Test S3 backend load — full round-trip via moto."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    # Seed data
    metadata = {"verstr": "1.0.0-dev.abc1234.def5678", "base_version": "1.0.0"}
    s3.put_object(
        Bucket="test-bucket",
        Key="test-prefix/my_app/1.0.0-dev.abc1234.def5678/metadata.yml",
        Body=yaml.dump(metadata).encode("utf-8"),
    )
    s3.put_object(
        Bucket="test-bucket",
        Key="test-prefix/my_app/1.0.0-dev.abc1234.def5678/working_tree.patch",
        Body=b"diff content",
    )

    from version_stamp.cli.snapshot import S3SnapshotStorage
    storage = S3SnapshotStorage("test-bucket", prefix="test-prefix")

    loaded_meta, loaded_patches = storage.load("my_app", "1.0.0-dev.abc1234.def5678")
    assert loaded_meta["verstr"] == "1.0.0-dev.abc1234.def5678"
    assert loaded_patches["working_tree"] == "diff content"


@mock_aws
def test_s3_snapshot_load_not_found():
    """Test S3 backend returns None for missing snapshot."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    from version_stamp.cli.snapshot import S3SnapshotStorage
    storage = S3SnapshotStorage("test-bucket")

    meta, patches = storage.load("my_app", "nonexistent")
    assert meta is None
    assert patches is None


@mock_aws
def test_s3_snapshot_list():
    """Test S3 backend list_snapshots — full round-trip via moto."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    from version_stamp.cli.snapshot import S3SnapshotStorage
    storage = S3SnapshotStorage("test-bucket")

    # Save two snapshots
    meta1 = {"verstr": "1.0.0-dev.aaa.bbb", "timestamp": "2025-01-01T00:00:00Z"}
    meta2 = {"verstr": "1.0.0-dev.ccc.ddd", "timestamp": "2025-01-02T00:00:00Z"}
    storage.save("my_app", "1.0.0-dev.aaa.bbb", meta1, {})
    storage.save("my_app", "1.0.0-dev.ccc.ddd", meta2, {})

    snapshots = storage.list_snapshots("my_app")
    assert len(snapshots) == 2
    assert snapshots[0]["verstr"] == "1.0.0-dev.aaa.bbb"
    assert snapshots[1]["verstr"] == "1.0.0-dev.ccc.ddd"


def test_s3_snapshot_endpoint_url():
    """Test S3 backend passes endpoint_url to boto3."""
    with mock_patch("boto3.client") as mock_boto:
        from version_stamp.cli.snapshot import S3SnapshotStorage
        S3SnapshotStorage("test-bucket", endpoint_url="http://localhost:9000")
        mock_boto.assert_called_once_with("s3", endpoint_url="http://localhost:9000")


def test_snapshot_actions_require_init(app_layout, capfd):
    """All snapshot actions should fail if vmn is not initialized."""
    name = app_layout.app_name

    assert _snapshot(name, action="list") != 0
    assert _snapshot(name, action="show", version="0.0.1-dev.abc1234.def5678") != 0
    assert _snapshot(name, action="restore", version="0.0.1-dev.abc1234.def5678") != 0
    assert _snapshot(name, action="diff", version="0.0.1-dev.abc1234.def5678",
                     to_version="current") != 0
    assert _snapshot(name, action="export", version="0.0.1-dev.abc1234.def5678",
                     output="/tmp/test_export") != 0


def test_snapshot_export_workdir(app_layout, capfd):
    """Export should materialize a snapshot into a working directory."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Create dirty state
    app_layout.write_file_commit_and_push("test_repo_0", "export_test.txt", "initial content")
    app_layout.write_file_commit_and_push(
        "test_repo_0", "export_test.txt", "modified content", commit=False
    )

    # Create snapshot
    capfd.readouterr()
    err = _snapshot(app_layout.app_name, note="export workdir test")
    assert err == 0
    verstr = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    # Export to directory
    export_dir = os.path.join(app_layout.repo_path, "_exported_workdir")
    capfd.readouterr()
    err = _snapshot(
        app_layout.app_name, action="export", version=verstr, output=export_dir
    )
    assert err == 0

    # Verify the export directory has actual files
    assert os.path.isdir(export_dir)
    assert os.path.isfile(os.path.join(export_dir, "vmn_metadata.yml"))
    assert os.path.isdir(os.path.join(export_dir, ".git"))


def test_snapshot_export_tarball(app_layout, capfd):
    """Export with .tar.gz output should create a tarball."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Create dirty state
    app_layout.write_file_commit_and_push("test_repo_0", "tar_test.txt", "content")
    app_layout.write_file_commit_and_push(
        "test_repo_0", "tar_test.txt", "modified", commit=False
    )

    # Create snapshot
    capfd.readouterr()
    err = _snapshot(app_layout.app_name, note="tarball test")
    assert err == 0
    verstr = _extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    # Export as tarball
    tar_path = os.path.join(app_layout.repo_path, "snapshot_export.tar.gz")
    capfd.readouterr()
    err = _snapshot(
        app_layout.app_name, action="export", version=verstr, output=tar_path
    )
    assert err == 0

    assert os.path.isfile(tar_path)
    with tarfile.open(tar_path, "r:gz") as tar:
        names = tar.getnames()
        assert any("vmn_metadata.yml" in n for n in names)
