"""``vmn-exp push <app>``: upload the local root's runs (typically recorded
under ``VMN_EXP_OFFLINE``) to the remote store, renaming on a collision."""
import json

import pytest
from helpers import _bootstrap, _exp
from s3_helpers import BUCKET, PREFIX, mocked_bucket, raw_keys, s3_storage

from vmn_exp.core import writer
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.s3 import S3SnapshotStorage
from vmn_exp.storage.uri import s3_uri

URI = s3_uri(BUCKET, PREFIX)
FOREIGN = "2025-05-05T00:00:00Z"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_EXPERIMENT_DIR",
                "VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXP_OFFLINE",
                "VMN_SNAPSHOT_METADATA", "VMN_RESUME_RUN_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(writer, "_WRITER_ID", None)
    with mocked_bucket(monkeypatch):
        yield


@pytest.fixture
def offline(app_layout, monkeypatch):
    """A bootstrapped repo recording offline, with the store configured."""
    _bootstrap(app_layout)
    monkeypatch.setenv("VMN_EXP_OFFLINE", "1")
    monkeypatch.setenv("VMN_EXPERIMENT_STORE", URI)
    return app_layout


def _run(app_layout, loss=1.0, parent=None):
    from vmn_exp.sdk import start_run

    with start_run(app_layout.app_name, parent=parent) as run:
        run.log_metric("loss", loss)
    return run.id


def _push(app_layout, *args):
    return _exp(app_layout.app_name, action="push", extra_args=list(args))


def _local(app_layout):
    return LocalSnapshotStorage(app_layout.repo_path, subdir="experiments")


def _lines(capfd):
    return capfd.readouterr().out.strip().splitlines()


def _foreign(app_layout, verstr):
    """The remote holds another run under *verstr*."""
    meta = _local(app_layout).load_metadata(app_layout.app_name, verstr)
    s3_storage().save(app_layout.app_name, verstr, dict(meta, timestamp=FOREIGN), {})


def test_push_uploads_offline_runs_even_while_offline(offline, capfd):
    first, second = _run(offline), _run(offline, 0.5)
    capfd.readouterr()
    assert _push(offline) == 0
    lines = _lines(capfd)
    assert f"{first}  new" in lines and f"{second}  new" in lines
    assert lines[-1] == "pushed 2, up-to-date 0, renamed 0, skipped 0, failed 0"
    remote = s3_storage()
    for verstr in (first, second):
        assert remote.load_metadata(offline.app_name, verstr)["verstr"] == verstr


def test_second_push_is_up_to_date(offline, capfd):
    verstr = _run(offline)
    assert _push(offline) == 0
    capfd.readouterr()
    assert _push(offline) == 0
    lines = _lines(capfd)
    assert f"{verstr}  up-to-date" in lines
    assert lines[-1] == "pushed 0, up-to-date 1, renamed 0, skipped 0, failed 0"


def test_version_flag_selects_runs(offline, capfd):
    first, second = _run(offline), _run(offline)
    capfd.readouterr()
    assert _push(offline, "-v", second) == 0
    assert _lines(capfd)[:-1] == [f"{second}  new"]
    assert s3_storage().load_metadata(offline.app_name, first) is None


def test_unknown_ref_fails(offline):
    _run(offline)
    assert _push(offline, "-v", "no-such-run") == 1
    assert raw_keys() == []


def test_no_remote_configured_fails(offline, monkeypatch, capfd):
    monkeypatch.delenv("VMN_EXPERIMENT_STORE")
    _run(offline)
    capfd.readouterr()
    assert _push(offline) == 1
    assert "remote store" in capfd.readouterr().err


def test_file_store_is_refused(offline, tmp_path, capfd):
    _run(offline)
    capfd.readouterr()
    assert _push(offline, "--store", f"file://{tmp_path}/elsewhere") == 1
    assert "rsync" in capfd.readouterr().err


def test_bucket_flag_names_the_target(offline, monkeypatch, capfd):
    monkeypatch.delenv("VMN_EXPERIMENT_STORE")
    verstr = _run(offline)
    assert _push(offline, "--bucket", BUCKET, "--prefix", PREFIX) == 0
    assert s3_storage().load_metadata(offline.app_name, verstr) is not None


def test_collision_is_renamed(offline, capfd):
    verstr = _run(offline)
    _foreign(offline, verstr)
    capfd.readouterr()
    assert _push(offline) == 0
    lines = _lines(capfd)
    (line,) = [x for x in lines if x.startswith(verstr)]
    status, new = line.split("  ", 1)[1].split(" -> ")
    assert status == "new" and new != verstr
    assert lines[-1] == "pushed 1, up-to-date 0, renamed 1, skipped 0, failed 0"
    assert _local(offline).exists(offline.app_name, new)
    assert s3_storage().load_metadata(offline.app_name, verstr)["timestamp"] == FOREIGN


def test_parent_pushed_before_child(offline, capfd):
    parent = _run(offline)
    child = _run(offline, parent=parent)
    _foreign(offline, parent)
    assert _push(offline, "-v", child, "-v", parent) == 0
    new_parent = _local(offline).load_metadata(offline.app_name, child)["parent"]
    assert new_parent != parent
    assert s3_storage().load_metadata(offline.app_name, child)["parent"] == new_parent


def test_json_output(offline, capfd):
    verstr = _run(offline)
    capfd.readouterr()
    assert _push(offline, "--json") == 0
    (row,) = json.loads(capfd.readouterr().out)
    assert (row["verstr"], row["status"], row["renamed_from"]) == (verstr, "new", "")


def test_dry_run_writes_nothing_remote(offline, capfd):
    fresh, taken = _run(offline), _run(offline)
    _foreign(offline, taken)
    keys = raw_keys()
    capfd.readouterr()
    assert _push(offline, "--dry-run") == 0
    lines = _lines(capfd)
    assert f"{fresh}  new" in lines and f"{taken}  collision" in lines
    assert raw_keys() == keys
    assert _local(offline).exists(offline.app_name, taken)


def test_dry_run_after_push_is_up_to_date(offline, capfd):
    verstr = _run(offline)
    assert _push(offline) == 0
    capfd.readouterr()
    assert _push(offline, "--dry-run") == 0
    assert f"{verstr}  up-to-date" in _lines(capfd)


def test_failed_push_exits_1(offline, monkeypatch, capfd):
    verstr = _run(offline)

    def boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(S3SnapshotStorage, "put_log_segment", boom)
    capfd.readouterr()
    assert _push(offline) == 1
    lines = _lines(capfd)
    assert f"{verstr}  failed (network down)" in lines
    assert lines[-1].endswith("failed 1")


def test_running_collision_is_skipped(offline, capfd):
    import yaml

    from vmn_exp._base import now_iso
    from vmn_exp.core.status import RUN_STATE_FILE

    verstr = _run(offline)
    state = yaml.safe_dump({"state": "running", "heartbeat": now_iso(),
                            "heartbeat_interval_sec": 30})
    _local(offline).save_file(offline.app_name, verstr, RUN_STATE_FILE, state)
    _foreign(offline, verstr)
    capfd.readouterr()
    assert _push(offline) == 0
    lines = _lines(capfd)
    assert any(x.startswith(f"{verstr}  skipped (running") for x in lines)
    assert lines[-1] == "pushed 0, up-to-date 0, renamed 0, skipped 1, failed 0"


def test_push_works_git_free(tmp_path, monkeypatch, capfd):
    import yaml

    from vmn_exp.cli.main import vmn_exp_run

    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(yaml.safe_dump(
        {"verstr": "1.2.0-dev.abc1234.0000000", "app_name": "trainer",
         "base_version": "1.2.0", "base_commit": "abc1234"}
    ))
    monkeypatch.chdir(image)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "exps"))
    monkeypatch.setenv("VMN_EXPERIMENT_STORE", URI)
    monkeypatch.setenv("VMN_EXP_OFFLINE", "1")
    assert vmn_exp_run(["exp", "create", "trainer"])[0] == 0
    assert raw_keys() == []
    capfd.readouterr()
    assert vmn_exp_run(["exp", "push", "trainer"])[0] == 0
    assert _lines(capfd)[-1].startswith("pushed 1,")
    assert len(s3_storage().list_snapshots("trainer")) == 1
