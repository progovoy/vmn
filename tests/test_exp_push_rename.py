"""A push whose remote name belongs to another run renames the run on both
sides (``.rN`` above every local and remote name), unless renaming it would
break something that points at the old name."""
import os

import pytest
from push_helpers import (
    APP, CODE, KEY, X, local_code_exists, local_log, local_root, make_run,
    remote_log, run_meta, set_state,
)
from s3_helpers import mocked_bucket, s3_storage

from vmn_exp._base import now_iso
from vmn_exp.core import push_rename
from vmn_exp.core.code_store import drop_unused_code, stored_code
from vmn_exp.core.push_code import CodePusher
from vmn_exp.core.push_ledger import PushLedger
from vmn_exp.core.push_rename import SKIPPED, push_or_rename
from vmn_exp.core.push_run import FAILED, NEW, UP_TO_DATE, UPDATE, push_run
from vmn_exp.core.status import RUN_STATE_FILE

FOREIGN = "2025-05-05T00:00:00Z"
CHILD = X + ".2"


@pytest.fixture
def target(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield s3_storage()


@pytest.fixture
def local(tmp_path):
    return local_root(tmp_path)


def _foreign(target, verstr=X):
    target.save(APP, verstr, run_meta(verstr, timestamp=FOREIGN), {})


def _push(local, target, verstr=X, **kw):
    ledger = PushLedger.for_target(local, APP, target)
    return push_or_rename(local, target, APP, verstr, ledger,
                          CodePusher(local, target, APP), **kw)


def test_collision_renames_both_sides(local, target, tmp_path):
    make_run(local, tmp_path)
    _foreign(target)
    outcome = _push(local, target)
    new = CODE + ".r2"
    assert (outcome.status, outcome.verstr, outcome.renamed_from) == (NEW, new, X)
    assert not local.exists(APP, X)
    meta = local.load_metadata(APP, new)
    assert (meta["verstr"], meta["renamed_from"]) == (new, X)
    assert target.load_metadata(APP, new) == meta
    assert remote_log(target, new) == local_log(local, new)
    assert target.load_metadata(APP, X)["timestamp"] == FOREIGN


def test_rename_target_avoids_local_names(local, target, tmp_path):
    make_run(local, tmp_path)
    make_run(local, tmp_path, verstr=CODE + ".r2", timestamp="2026-03-03T00:00:00Z")
    _foreign(target)
    _foreign(target, CODE + ".r3")
    assert _push(local, target).verstr == CODE + ".r4"


def test_rename_keeps_code_verstr_prefix_so_prune_keeps_code(local, target, tmp_path):
    make_run(local, tmp_path)
    _foreign(target)
    new = _push(local, target).verstr
    assert new.startswith(CODE + ".")
    drop_unused_code(local, APP, {CODE})
    drop_unused_code(target, APP, {CODE})
    assert local_code_exists(local)
    assert stored_code(target, APP, KEY) is not None


def test_rename_rewrites_children_parent_locally_and_remotely(local, target, tmp_path):
    make_run(local, tmp_path)
    make_run(local, tmp_path, verstr=CHILD, timestamp="2026-01-02T00:00:00Z", parent=X)
    _foreign(target)
    new = _push(local, target).verstr
    assert local.load_metadata(APP, CHILD)["parent"] == new
    assert _push(local, target, CHILD).status == NEW
    assert target.load_metadata(APP, CHILD)["parent"] == new


def _assert_skipped(local, target, outcome, reason):
    assert outcome.status == SKIPPED
    assert reason in outcome.detail
    assert local.exists(APP, X)
    assert target.load_metadata(APP, X)["timestamp"] == FOREIGN


def test_running_run_with_collision_is_skipped_not_renamed(local, target, tmp_path):
    make_run(local, tmp_path)
    set_state(local, X, "running", heartbeat=now_iso(), heartbeat_interval_sec=30)
    _foreign(target)
    _assert_skipped(local, target, _push(local, target), "running")


def test_stuck_run_with_collision_is_skipped(local, target, tmp_path):
    make_run(local, tmp_path)
    set_state(local, X, "running", heartbeat="2020-01-01T00:00:00Z")
    state = os.path.join(local._snapshot_dir(APP, X), RUN_STATE_FILE)
    os.utime(state, (1577836800, 1577836800))
    _foreign(target)
    _assert_skipped(local, target, _push(local, target), "stuck")


def test_registry_referenced_run_not_renamed(local, target, tmp_path):
    make_run(local, tmp_path)
    _foreign(target)
    outcome = _push(local, target, registered={(APP, X)})
    _assert_skipped(local, target, outcome, "registered")


def test_sweep_outer_run_not_renamed(local, target, tmp_path):
    make_run(local, tmp_path, sweep={"method": "grid"})
    _foreign(target)
    _assert_skipped(local, target, _push(local, target), "sweep outer run collides")


def test_rename_recovers_after_crash_between_claim_and_local_move(
    local, target, tmp_path, monkeypatch
):
    make_run(local, tmp_path)
    _foreign(target)
    move = push_rename._move_local

    def crash(*args, **kwargs):
        raise OSError("killed")

    monkeypatch.setattr(push_rename, "_move_local", crash)
    assert _push(local, target).status == FAILED
    new = CODE + ".r2"
    assert target.load_metadata(APP, new) is not None
    monkeypatch.setattr(push_rename, "_move_local", move)
    outcome = _push(local, target)
    assert (outcome.status, outcome.verstr, outcome.renamed_from) == (UPDATE, new, X)
    assert target.load_metadata(APP, CODE + ".r3") is None
    assert remote_log(target, new) == local_log(local, new)


def test_rename_ledger_entry_moves(local, target, tmp_path):
    make_run(local, tmp_path)
    _foreign(target)
    new = _push(local, target).verstr
    ledger = PushLedger.for_target(local, APP, target)
    assert ledger.get(X) is None
    entry = ledger.get(new)
    assert entry["complete"] and entry["remote_verstr"] == new
    assert "pending_target" not in entry
    assert push_run(local, target, APP, new, ledger).status == UP_TO_DATE
