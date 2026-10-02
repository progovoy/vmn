"""Registry data model for datasets and recorded usage (plan 06).

Covers: registry URIs, the ``<model>-uses`` sibling record and its fold,
header ``kind``, reference versions (no ``run_ref``), ``list_models(kind=)``,
and the ``kind`` field of ``models_for_run``.
"""
import random

import pytest

from vmn_exp.registry.fold import fold_registry, fold_uses
from vmn_exp.registry.log import read_entries, read_uses, record_use
from vmn_exp.registry.names import (
    HEADER_RECORD,
    USES_RECORD,
    parse_registry_uri,
    parse_version_record,
    registry_uri,
)
from vmn_exp.registry.store import (
    ensure_model,
    get_version,
    list_models,
    load_header,
    model_kind,
    register_version,
    registry_storage,
)
from vmn_exp.registry.view import models_for_run, registered_runs
from vmn_exp.registry import view
from vmn_exp.storage.local import LocalSnapshotStorage


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), area="runs")


def _use(version, app, verstr, ts, writer="w1", pos=0):
    return {"type": "use", "version": version, "run": {"app": app, "verstr": verstr},
            "ts": ts, "writer": writer, "pos": pos}


# -- names ------------------------------------------------------------------

def test_registry_uri_round_trip():
    uri = registry_uri("imagenet", 3)
    assert uri == "vmn-registry://imagenet@3"
    assert parse_registry_uri(uri) == ("imagenet", 3)


@pytest.mark.parametrize("uri", [
    "vmn://app/1.0.0/x", "s3://b/k", "vmn-registry://m@prod", "vmn-registry://m@0",
    "vmn-registry://m", "vmn-registry://@3", "vmn-registry://bad-name@3", None, "",
])
def test_parse_registry_uri_rejects_other_schemes_and_bad_numbers(uri):
    assert parse_registry_uri(uri) is None


def test_header_and_uses_records_are_never_version_records():
    assert parse_version_record(USES_RECORD) is None
    assert parse_version_record(HEADER_RECORD) is None


# -- fold_uses ----------------------------------------------------------------

def test_fold_uses_deduped_earliest_ts():
    entries = [
        _use(1, "a", "0.1", "2026-01-02T00:00:00.000000", pos=0),
        _use(1, "a", "0.1", "2026-01-01T00:00:00.000000", pos=1),
        _use(1, "b", "0.2", "2026-01-03T00:00:00.000000", pos=2),
        _use(2, "a", "0.1", "2026-01-04T00:00:00.000000", pos=3),
        {"type": "alias", "alias": "x", "version": 1},
        "garbage",
    ]
    assert fold_uses(entries) == {
        1: [
            {"app": "a", "verstr": "0.1", "ts": "2026-01-01T00:00:00.000000"},
            {"app": "b", "verstr": "0.2", "ts": "2026-01-03T00:00:00.000000"},
        ],
        2: [{"app": "a", "verstr": "0.1", "ts": "2026-01-04T00:00:00.000000"}],
    }


def test_fold_uses_chunking_invariant():
    entries = [
        _use(n % 3 + 1, f"app{n % 2}", f"0.{n % 4}", f"2026-01-0{n % 9 + 1}T00:00:00.000000",
             writer=f"w{n % 2}", pos=n)
        for n in range(20)
    ]
    expected = fold_uses(entries)
    for seed in range(5):
        shuffled = list(entries)
        random.Random(seed).shuffle(shuffled)
        assert fold_uses(shuffled) == expected
    assert fold_uses(entries[10:] + entries[:10]) == expected


# -- record_use ----------------------------------------------------------------

def test_use_entries_not_in_model_audit(tmp_path):
    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    n = register_version(storage, "resnet", {"app": "a", "verstr": "0.1"})
    record_use(storage, "resnet", n, "consumer", "0.9")
    assert fold_registry(read_entries(storage, "resnet"))["audit"] == []
    uses = read_uses(storage, "resnet")
    assert list(uses) == [n]
    assert [(u["app"], u["verstr"]) for u in uses[n]] == [("consumer", "0.9")]


def test_record_use_same_run_twice_writes_one_entry(tmp_path):
    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    n = register_version(storage, "resnet", {"app": "a", "verstr": "0.1"})
    record_use(storage, "resnet", n, "consumer", "0.9")
    record_use(storage, "resnet", n, "consumer", "0.9")
    assert len(read_entries(storage, "resnet", USES_RECORD)) == 1


def test_use_entry_does_not_invalidate_run_models_cache(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    n = register_version(storage, "resnet", {"app": "a", "verstr": "0.1"})
    assert models_for_run(storage, "a", "0.1")[0]["version"] == n

    scans = []
    real_scan = view._scan_run_models
    monkeypatch.setattr(view, "_scan_run_models", lambda s: scans.append(1) or real_scan(s))
    record_use(storage, "resnet", n, "consumer", "0.9")
    record_use(storage, "resnet", n, "consumer", "1.0")
    models_for_run(storage, "a", "0.1")
    assert scans == []


# -- kind ----------------------------------------------------------------------

def test_ensure_model_writes_kind_default_model(tmp_path):
    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    ensure_model(storage, "imagenet", kind="dataset")
    assert load_header(storage, "resnet")["kind"] == "model"
    assert model_kind(storage, "resnet") == "model"
    assert model_kind(storage, "imagenet") == "dataset"
    assert model_kind(storage, "absent") is None


def test_ensure_model_kind_mismatch_raises(tmp_path):
    storage = _storage(tmp_path)
    ensure_model(storage, "imagenet", kind="dataset")
    ensure_model(storage, "imagenet", kind="dataset")  # idempotent
    with pytest.raises(ValueError, match="dataset"):
        ensure_model(storage, "imagenet")


def test_ensure_model_rejects_unknown_kind(tmp_path):
    with pytest.raises(ValueError):
        ensure_model(_storage(tmp_path), "x", kind="table")


def test_legacy_header_kind_is_model(tmp_path):
    storage = _storage(tmp_path)
    registry_storage(storage).create_exclusive(
        "old", HEADER_RECORD, {"model": "old", "type": "model_header"}, {}
    )
    assert model_kind(storage, "old") == "model"
    ensure_model(storage, "old")  # no mismatch
    with pytest.raises(ValueError):
        ensure_model(storage, "old", kind="dataset")


def test_register_version_without_run_ref_stores_uri_digest(tmp_path):
    storage = _storage(tmp_path)
    ensure_model(storage, "imagenet", kind="dataset")
    n = register_version(
        storage, "imagenet", uri="s3://b/imagenet/", digest="sha256:ab", size=10, files=2,
    )
    meta = get_version(storage, "imagenet", n)
    assert "run_ref" not in meta
    assert (meta["uri"], meta["digest"], meta["size"], meta["files"]) == (
        "s3://b/imagenet/", "sha256:ab", 10, 2,
    )


def test_list_models_kind_filter(tmp_path):
    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    ensure_model(storage, "imagenet", kind="dataset")
    record_use(storage, "resnet", 1, "a", "0.1")
    assert list_models(storage) == ["imagenet", "resnet"]
    assert list_models(storage, kind="model") == ["resnet"]
    assert list_models(storage, kind="dataset") == ["imagenet"]


def test_registered_runs_ignores_reference_versions(tmp_path):
    storage = _storage(tmp_path)
    ensure_model(storage, "imagenet", kind="dataset")
    register_version(storage, "imagenet", uri="s3://b/x", digest="sha256:ab")
    ensure_model(storage, "resnet")
    register_version(storage, "resnet", {"app": "a", "verstr": "0.1"})
    assert registered_runs(storage) == {("a", "0.1")}


def test_models_for_run_includes_kind(tmp_path):
    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    register_version(storage, "resnet", {"app": "a", "verstr": "0.1"}, artifact_path="m.pkl")
    ensure_model(storage, "prepped", kind="dataset")
    register_version(storage, "prepped", {"app": "a", "verstr": "0.1"}, artifact_path="d.csv")
    kinds = {m["model"]: m["kind"] for m in models_for_run(storage, "a", "0.1")}
    assert kinds == {"prepped": "dataset", "resnet": "model"}


def test_model_state_carries_kind_and_reference_fields(tmp_path):
    from vmn_exp.registry.view import model_state

    storage = _storage(tmp_path)
    ensure_model(storage, "imagenet", kind="dataset")
    register_version(storage, "imagenet", uri="s3://b/x", digest="sha256:ab", size=3, files=1)
    state = model_state(storage, "imagenet")
    assert state["kind"] == "dataset"
    row = state["versions"][0]
    assert (row["run_ref"], row["uri"], row["digest"], row["size"], row["files"]) == (
        None, "s3://b/x", "sha256:ab", 3, 1,
    )
