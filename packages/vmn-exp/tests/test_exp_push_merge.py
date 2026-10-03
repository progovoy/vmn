"""``push_run`` against remote state that already exists: an online mirror of
the run, orphan objects older versions leaked, foreign bytes, mutable files
and fields changed on either side, and other backends."""
import pytest
import yaml
from push_helpers import (
    APP, WRITER, X, add_lines, line, local_log, local_root, make_run, remote_log,
    run_meta, set_state,
)
from s3_helpers import mocked_bucket, put_raw, s3_storage

from object_store_fakes import FakeContainerClient, FakeGCSClient, MatchConditions
from vmn_exp.core.alerts.transitions import ALERTS_FILE
from vmn_exp.core.manage import set_archived
from vmn_exp.core.push_run import COLLISION, FAILED, NEW, UPDATE, push_run
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.files import log_object_name


@pytest.fixture
def target(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield s3_storage()


@pytest.fixture
def local(tmp_path):
    return local_root(tmp_path)


def _key(target, name):
    return f"{target._key_prefix(APP, X)}/{name}"


# -- adopting existing remote state ------------------------------------------


def test_online_mirrored_run_is_same_run(local, target, tmp_path):
    make_run(local, tmp_path)
    target.save(APP, X, local.load_metadata(APP, X), {})
    put_raw(_key(target, log_object_name(WRITER)), local_log(local))
    assert push_run(local, target, APP, X).status == UPDATE
    assert remote_log(target) == local_log(local)


def test_orphan_log_from_old_versions_is_adopted(local, target, tmp_path):
    make_run(local, tmp_path)
    put_raw(_key(target, log_object_name(WRITER)), line(1).encode())
    assert push_run(local, target, APP, X).status == NEW
    assert remote_log(target) == local_log(local)


def test_foreign_bytes_under_same_writer_id_fail_loudly(local, target, tmp_path):
    make_run(local, tmp_path)
    put_raw(_key(target, log_object_name(WRITER)), line(9).encode())
    outcome = push_run(local, target, APP, X)
    assert outcome.status == FAILED
    assert WRITER in outcome.detail and "VMN_WRITER_ID" in outcome.detail
    assert remote_log(target) == line(9).encode()


def test_foreign_record_of_the_same_name_is_a_collision(local, target, tmp_path):
    make_run(local, tmp_path)
    target.save(APP, X, run_meta(timestamp="2026-09-09T00:00:00Z"), {})
    assert push_run(local, target, APP, X).status == COLLISION
    assert target.load_file(APP, X, RUN_STATE_FILE) is None
    assert target.list_artifacts(APP, X) == []


# -- mutable files and fields ---------------------------------------------------


def test_local_run_state_change_is_pushed(local, target, tmp_path):
    make_run(local, tmp_path)
    set_state(local, X, "running")
    push_run(local, target, APP, X)
    set_state(local, X, "finished", exit_code=1)
    push_run(local, target, APP, X)
    assert target.load_file(APP, X, RUN_STATE_FILE) == local.load_file(
        APP, X, RUN_STATE_FILE
    )


def test_remote_run_state_changed_elsewhere_is_not_clobbered(local, target, tmp_path):
    make_run(local, tmp_path)
    push_run(local, target, APP, X)
    target.save_file(APP, X, RUN_STATE_FILE, "state: elsewhere\n")
    set_state(local, X, "finished", exit_code=2)
    outcome = push_run(local, target, APP, X)
    assert target.load_file(APP, X, RUN_STATE_FILE) == b"state: elsewhere\n"
    assert any(RUN_STATE_FILE in w for w in outcome.warnings)


def _alerts(storage):
    return set(yaml.safe_load(storage.load_file(APP, X, ALERTS_FILE))["sent"])


def test_alerts_sent_merged_as_union(local, target, tmp_path):
    make_run(local, tmp_path)
    local.save_file(APP, X, ALERTS_FILE, yaml.dump({"sent": {"a": "t1"}}))
    push_run(local, target, APP, X)
    target.save_file(APP, X, ALERTS_FILE, yaml.dump({"sent": {"a": "t1", "b": "t2"}}))
    local.save_file(APP, X, ALERTS_FILE, yaml.dump({"sent": {"a": "t1", "c": "t3"}}))
    push_run(local, target, APP, X)
    assert _alerts(target) == {"a", "b", "c"} == _alerts(local)


def test_local_archive_propagates(local, target, tmp_path):
    make_run(local, tmp_path)
    push_run(local, target, APP, X)
    set_archived(local, APP, X)
    push_run(local, target, APP, X)
    assert target.load_metadata(APP, X)["archived"] is True


def test_remote_archive_kept_when_local_unchanged(local, target, tmp_path):
    make_run(local, tmp_path)
    push_run(local, target, APP, X)
    set_archived(target, APP, X)
    add_lines(local, X, [line(3)])  # a local change, so the push runs at all
    outcome = push_run(local, target, APP, X)
    assert target.load_metadata(APP, X)["archived"] is True
    assert local.load_metadata(APP, X)["archived"] is True
    assert outcome.warnings == []
    set_archived(local, APP, X, archived=False)
    push_run(local, target, APP, X)
    assert "archived" not in target.load_metadata(APP, X)


def test_conflicting_archive_remote_wins_with_warning(local, target, tmp_path):
    make_run(local, tmp_path)
    target.save(APP, X, dict(local.load_metadata(APP, X), archived=True), {})
    outcome = push_run(local, target, APP, X)
    assert target.load_metadata(APP, X)["archived"] is True
    assert local.load_metadata(APP, X)["archived"] is True
    assert any("archived" in w for w in outcome.warnings)


def test_conflicting_note_remote_wins_with_warning(local, target, tmp_path):
    make_run(local, tmp_path, note="base")
    push_run(local, target, APP, X)
    target.update_note(APP, X, "theirs")
    local.update_note(APP, X, "mine")
    outcome = push_run(local, target, APP, X)
    assert target.load_metadata(APP, X)["note"] == "theirs"
    assert local.load_metadata(APP, X)["note"] == "theirs"
    assert any("note" in w for w in outcome.warnings)


# -- logs --------------------------------------------------------------------


def test_finished_run_segments_compacted(local, target, tmp_path):
    make_run(local, tmp_path)
    set_state(local, X, "running")
    push_run(local, target, APP, X)
    add_lines(local, X, [line(3)])
    push_run(local, target, APP, X)
    assert len(target.log_objects(APP, X, WRITER)) == 2
    set_state(local, X, "finished", exit_code=0)
    push_run(local, target, APP, X)
    assert len(target.log_objects(APP, X, WRITER)) == 1
    assert remote_log(target) == local_log(local)


# -- backends ----------------------------------------------------------------


def _gcs():
    from vmn_exp.storage.gcs import GCSSnapshotStorage

    return GCSSnapshotStorage("bkt", prefix="p", client=FakeGCSClient())


def _azure():
    from vmn_exp.storage.azure import AzureSnapshotStorage

    return AzureSnapshotStorage(
        "bkt", prefix="p", container=FakeContainerClient("bkt"),
        if_not_modified=MatchConditions.IfNotModified,
    )


@pytest.mark.parametrize("make_target", [_gcs, _azure], ids=["gs", "az"])
def test_push_to_gcs_and_azure(local, tmp_path, make_target):
    store = make_target()
    make_run(local, tmp_path)
    assert push_run(local, store, APP, X).status == NEW
    add_lines(local, X, [line(3)])
    assert push_run(local, store, APP, X).status == UPDATE
    assert remote_log(store) == local_log(local)
    assert store.list_artifacts(APP, X) == local.list_artifacts(APP, X)
    assert store.load(APP, X)[1]["untracked_files"] == b"tarball"
