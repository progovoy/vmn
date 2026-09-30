"""Tests for vmn_exp/registry/names.py and vmn_exp/registry/fold.py (C1).

Eight tests: latest wins, tie-break independent of order, tombstone removal,
chunking-invariant fold, skew bump, parse refs, name validation, audit ordered.
"""
import random
import pytest

from vmn_exp.registry.names import (
    valid_model_name,
    valid_alias_name,
    version_record_name,
    parse_version_record,
    parse_ref,
)
from vmn_exp.registry.fold import fold_registry, next_ts


# ---------------------------------------------------------------------------
# 1. latest wins
# ---------------------------------------------------------------------------

def test_latest_wins():
    """Later (ts, writer, pos) wins for the same alias."""
    entries = [
        {
            "type": "alias", "alias": "prod", "version": 1,
            "ts": "2024-01-01T00:00:00.000000", "writer": "w1", "pos": 0,
        },
        {
            "type": "alias", "alias": "prod", "version": 2,
            "ts": "2024-01-02T00:00:00.000000", "writer": "w1", "pos": 0,
        },
    ]
    fold = fold_registry(entries)
    assert fold["aliases"]["prod"] == 2


# ---------------------------------------------------------------------------
# 2. tie-break independent of dict/list order
# ---------------------------------------------------------------------------

def test_tie_break_independent_of_dict_order():
    """Same ts + writer; higher pos wins regardless of input order."""
    entry_lo = {
        "type": "alias", "alias": "prod", "version": 1,
        "ts": "2024-01-01T00:00:00.000000", "writer": "w1", "pos": 0,
    }
    entry_hi = {
        "type": "alias", "alias": "prod", "version": 2,
        "ts": "2024-01-01T00:00:00.000000", "writer": "w1", "pos": 1,
    }
    assert fold_registry([entry_lo, entry_hi])["aliases"]["prod"] == 2
    assert fold_registry([entry_hi, entry_lo])["aliases"]["prod"] == 2


# ---------------------------------------------------------------------------
# 3. tombstone removal
# ---------------------------------------------------------------------------

def test_tombstone_removal():
    """An alias entry with version=None removes the alias from fold['aliases']."""
    entries = [
        {
            "type": "alias", "alias": "staging", "version": 3,
            "ts": "2024-01-01T00:00:00.000000", "writer": "w1", "pos": 0,
        },
        {
            "type": "alias", "alias": "staging", "version": None,
            "ts": "2024-01-02T00:00:00.000000", "writer": "w1", "pos": 0,
        },
    ]
    fold = fold_registry(entries)
    assert "staging" not in fold["aliases"]


# ---------------------------------------------------------------------------
# 4. chunking-invariant fold
# ---------------------------------------------------------------------------

def test_chunking_invariant_fold():
    """fold(entries) == fold(shuffled_entries) for aliases and status."""
    entries = [
        {
            "type": "alias", "alias": "prod", "version": 1,
            "ts": "2024-01-01T00:00:00.000000", "writer": "w1", "pos": 0,
        },
        {
            "type": "alias", "alias": "prod", "version": 2,
            "ts": "2024-01-02T00:00:00.000000", "writer": "w1", "pos": 0,
        },
        {
            "type": "status", "version": 1, "status": "deprecated",
            "ts": "2024-01-03T00:00:00.000000", "writer": "w1", "pos": 0,
        },
        {
            "type": "alias", "alias": "canary", "version": 2,
            "ts": "2024-01-01T00:00:00.000000", "writer": "w2", "pos": 0,
        },
    ]
    expected = fold_registry(entries)
    shuffled = entries.copy()
    random.shuffle(shuffled)
    result = fold_registry(shuffled)
    assert result["aliases"] == expected["aliases"]
    assert result["status"] == expected["status"]


# ---------------------------------------------------------------------------
# 5. skew bump
# ---------------------------------------------------------------------------

def test_skew_bump():
    """next_ts returns a ts strictly greater than prev_ts when clock is skewed."""
    prev = "2024-01-01T12:00:00.000000"
    now_behind = "2024-01-01T11:00:00.000000"   # clock behind prev
    now_ahead = "2024-01-02T00:00:00.000000"    # clock well ahead of prev

    result_behind = next_ts(prev, now_behind)
    assert result_behind > prev  # bumped to prev + 1µs

    result_ahead = next_ts(prev, now_ahead)
    assert result_ahead == now_ahead  # no bump needed

    # None prev_ts: just use now
    assert next_ts(None, now_ahead) == now_ahead


# ---------------------------------------------------------------------------
# 6. parse refs
# ---------------------------------------------------------------------------

def test_parse_refs():
    """parse_ref handles all four ref forms correctly."""
    assert parse_ref("mymodel@prod") == ("mymodel", "alias", "prod")
    assert parse_ref("mymodel@3") == ("mymodel", "version", 3)
    assert parse_ref("mymodel@latest") == ("mymodel", "latest", None)
    assert parse_ref("mymodel") == ("mymodel", "latest", None)
    # multi-digit version
    assert parse_ref("m@42") == ("m", "version", 42)
    # alias that starts with a digit but is not pure digits
    assert parse_ref("m@v2-stable") == ("m", "alias", "v2-stable")


# ---------------------------------------------------------------------------
# 7. name validation
# ---------------------------------------------------------------------------

def test_name_validation():
    """Model and alias name rules."""
    # valid model names
    assert valid_model_name("my_model")
    assert valid_model_name("MyModel123")
    assert valid_model_name("model.extra")       # dot allowed, not .v<digits> suffix
    assert valid_model_name("model.v2extra")     # not pure .v<digits> suffix

    # invalid model names
    assert not valid_model_name("")              # empty
    assert not valid_model_name("my-model")     # hyphen forbidden
    assert not valid_model_name(".model")       # leading dot
    assert not valid_model_name("model.v2")     # ends with .v<digits> — ambiguous
    assert not valid_model_name("model.v123")   # ends with .v<digits>

    # valid alias names
    assert valid_alias_name("production")
    assert valid_alias_name("v2-stable")         # hyphens OK in aliases
    assert valid_alias_name("release.2024")

    # invalid alias names
    assert not valid_alias_name("")              # empty
    assert not valid_alias_name("latest")        # reserved keyword
    assert not valid_alias_name("42")            # pure digits reserved
    assert not valid_alias_name("0")             # pure digit


# ---------------------------------------------------------------------------
# 8. audit ordered
# ---------------------------------------------------------------------------

def test_audit_ordered():
    """audit list is sorted ascending by (ts, writer, pos)."""
    entries = [
        {
            "type": "alias", "alias": "prod", "version": 2,
            "ts": "2024-01-02T00:00:00.000000", "writer": "w1", "pos": 0,
        },
        {
            "type": "alias", "alias": "prod", "version": 1,
            "ts": "2024-01-01T00:00:00.000000", "writer": "w1", "pos": 0,
        },
        {
            "type": "status", "version": 1, "status": "deprecated",
            "ts": "2024-01-03T00:00:00.000000", "writer": "w1", "pos": 0,
        },
    ]
    fold = fold_registry(entries)
    assert len(fold["audit"]) == 3
    keys = [(e["ts"], e["writer"], e["pos"]) for e in fold["audit"]]
    assert keys == sorted(keys)
