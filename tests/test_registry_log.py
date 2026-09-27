"""Tests for vmn_exp/registry/log.py (C3).

Seven tests: set alias visible in fold, move alias, remove alias,
test_second_host_sees_alias_move (two local storages sharing a dir),
test_expect_mismatch_raises, status deprecate,
test_delete_version_with_alias_refused.
"""
import pytest

from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.registry.fold import fold_registry
from vmn_exp.registry.log import (
    REGISTRY_APP,
    read_entries,
    remove_alias,
    set_alias,
    set_version_status,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _local(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), subdir="registry")


def _make_model(storage, model):
    """Seed the model record so append_log_entry has a directory to write into."""
    storage.save(REGISTRY_APP, model, {"verstr": model}, {})


# ---------------------------------------------------------------------------
# 1. set alias visible in fold
# ---------------------------------------------------------------------------

def test_set_alias_visible_in_fold(tmp_path):
    st = _local(tmp_path)
    _make_model(st, "resnet")
    set_alias(st, "resnet", "prod", 1)
    fold = fold_registry(read_entries(st, "resnet"))
    assert fold["aliases"]["prod"] == 1


# ---------------------------------------------------------------------------
# 2. move alias
# ---------------------------------------------------------------------------

def test_move_alias(tmp_path):
    st = _local(tmp_path)
    _make_model(st, "resnet")
    set_alias(st, "resnet", "prod", 1)
    set_alias(st, "resnet", "prod", 2)
    fold = fold_registry(read_entries(st, "resnet"))
    assert fold["aliases"]["prod"] == 2


# ---------------------------------------------------------------------------
# 3. remove alias
# ---------------------------------------------------------------------------

def test_remove_alias(tmp_path):
    st = _local(tmp_path)
    _make_model(st, "resnet")
    set_alias(st, "resnet", "staging", 3)
    remove_alias(st, "resnet", "staging")
    fold = fold_registry(read_entries(st, "resnet"))
    assert "staging" not in fold["aliases"]


# ---------------------------------------------------------------------------
# 4. second host sees alias move
# ---------------------------------------------------------------------------

def test_second_host_sees_alias_move(tmp_path, monkeypatch):
    """Two storages sharing the same directory: host2 sees host1's alias write."""
    import vmn_exp.core.writer as ew

    st1 = _local(tmp_path)
    _make_model(st1, "bert")

    # host1 sets alias → version 1
    monkeypatch.setenv("VMN_WRITER_ID", "host1")
    ew._WRITER_ID = None
    set_alias(st1, "bert", "prod", 1)

    # host2 — fresh storage object at the same path, different writer id
    st2 = _local(tmp_path)
    monkeypatch.setenv("VMN_WRITER_ID", "host2")
    ew._WRITER_ID = None
    set_alias(st2, "bert", "prod", 2)

    # fold should reflect host2's later move to version 2
    ew._WRITER_ID = None
    fold = fold_registry(read_entries(st2, "bert"))
    assert fold["aliases"]["prod"] == 2

    # also verify host1's entry is present (two entries total)
    entries = read_entries(st2, "bert")
    assert sum(1 for e in entries if e.get("type") == "alias") == 2


# ---------------------------------------------------------------------------
# 5. expect mismatch raises
# ---------------------------------------------------------------------------

def test_expect_mismatch_raises(tmp_path):
    st = _local(tmp_path)
    _make_model(st, "gpt")

    # alias absent but caller expects version 1 → error
    with pytest.raises(ValueError, match="Expected alias"):
        set_alias(st, "gpt", "prod", 2, expect=1)

    # set alias to 1
    set_alias(st, "gpt", "prod", 1)

    # alias exists but caller expects "none" → error
    with pytest.raises(ValueError, match="Expected alias"):
        set_alias(st, "gpt", "prod", 2, expect="none")

    # correct expect → succeeds
    set_alias(st, "gpt", "prod", 2, expect=1)
    assert fold_registry(read_entries(st, "gpt"))["aliases"]["prod"] == 2


# ---------------------------------------------------------------------------
# 6. status deprecate
# ---------------------------------------------------------------------------

def test_status_deprecate(tmp_path):
    st = _local(tmp_path)
    _make_model(st, "vgg")
    set_version_status(st, "vgg", 1, "deprecated")
    fold = fold_registry(read_entries(st, "vgg"))
    assert fold["status"][1] == "deprecated"


# ---------------------------------------------------------------------------
# 7. delete version with alias refused
# ---------------------------------------------------------------------------

def test_delete_version_with_alias_refused(tmp_path):
    st = _local(tmp_path)
    _make_model(st, "efficientnet")
    set_alias(st, "efficientnet", "prod", 2)

    # version 2 still aliased → delete must raise
    with pytest.raises(ValueError, match="aliases"):
        set_version_status(st, "efficientnet", 2, "deleted")

    # remove the alias first, then delete succeeds
    remove_alias(st, "efficientnet", "prod")
    set_version_status(st, "efficientnet", 2, "deleted")
    fold = fold_registry(read_entries(st, "efficientnet"))
    assert fold["status"][2] == "deleted"
    assert "prod" not in fold["aliases"]
