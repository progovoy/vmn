"""``vmn-exp migrate`` converts v1 ``metrics`` log entries to compacted
``metrics/<writer>.vmx`` files (docs/plans/12-columnar-metrics.md §9)."""
import json
import math

import boto3
import pytest
import yaml
from moto import mock_aws

from migrate_fixtures import APP, LocalRaw, ObjectRaw, local_key, object_key
from vmn_exp.cli import migrate as migrate_mod
from vmn_exp.cli.migrate import run_migrate
from vmn_exp.core.fold import fold_log, fold_metrics
from vmn_exp.core.log import load_log, metric_series
from vmn_exp.core.metric_time import us_to_iso
from vmn_exp.core.rewind import drop_rewound
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.store_marker import forget_checked

T0 = 1_700_000_000_000_001


@pytest.fixture(autouse=True)
def _fresh_marker_cache():
    forget_checked()
    yield
    forget_checked()


def _ts(i):
    return us_to_iso(T0 + i * 1_000_003)


def _m(i, values, step=None, **extra):
    entry = {"timestamp": _ts(i), "type": "metrics", "values": values, **extra}
    if step is not None:
        entry["step"] = step
    return entry


W1 = [
    {"timestamp": _ts(0), "type": "create"},
    {"timestamp": _ts(1), "type": "params", "params": {"lr": 0.1}},
    _m(2, {"loss": 1.0, "acc": 0.1}, step=0),
    _m(3, {"loss": 0.8}, step=1),
    _m(4, {"loss": float("nan"), "acc": float("inf")}, step=2),
    _m(5, {"lr_now": 0.01}),
    _m(6, {"loss": 0.5}),
    _m(7, {"loss": 0.4, "acc": float("-inf")}, step=3),
    {"timestamp": _ts(8), "type": "rewind", "step": 1},
    _m(9, {"loss": 0.3}, step=2),
]
W1_SEG = [_m(10, {"loss": 0.2, "acc": 0.9}, step=3),
          {"timestamp": _ts(11), "type": "note", "text": "done"}]
LEGACY = [_m(12, {"old": 7.0}, step=0), _m(13, {"old": 8.0}, step=1, inherited=True)]
METRIC_KEYS = ("log/w1.jsonl", "log/w1@000001.jsonl", "log/v1.jsonl")


def _jsonl(entries):
    return "".join(json.dumps(e) + "\n" for e in entries).encode()


def _run_files(meta_extra=None, state=None):
    meta = {"verstr": "r1", "code_verstr": "c1", "app_name": APP,
            "timestamp": _ts(0), **(meta_extra or {})}
    return {
        "metadata.yml": yaml.safe_dump(meta).encode(),
        "run_state.yml": yaml.safe_dump(state or {"state": "finished", "exit_code": 0}).encode(),
        "log.w1.jsonl": _jsonl(W1),
        "log.w1@000001.jsonl": _jsonl(W1_SEG),
        "log.yml": yaml.safe_dump(LEGACY).encode(),
    }


def _expected():
    merged = drop_rewound(sorted(W1 + W1_SEG + LEGACY, key=lambda e: e["timestamp"]))
    return metric_series(merged), fold_metrics(fold_log(merged))


def _norm(value):
    if isinstance(value, float) and math.isnan(value):
        return "nan"
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def _assert_readers_match(storage):
    from vmn_exp.core.series_reader import SeriesReader
    from vmn_exp.sdk.reader import get_run, list_runs

    series, (folded, summary) = _expected()
    run = get_run(APP, "r1", storage=storage)
    assert _norm(run["series"]) == _norm(series)
    assert _norm(run["metrics"]) == _norm(folded)
    assert _norm(run["metric_summary"]) == _norm(summary)
    log = load_log(storage, APP, "r1")
    assert _norm(metric_series(SeriesReader.from_storage(storage, APP, "r1", log=log))) \
        == _norm(series)
    [row] = list_runs(APP, storage=storage)
    assert _norm(row["metrics"]) == _norm(folded)
    assert _norm(row["metric_summary"]) == _norm(summary)


def _v1_local(tmp_path, **kw):
    raw = LocalRaw(tmp_path)
    for name, data in _run_files(**kw).items():
        raw.put(f"{local_key(('run',), 'r1')}/{name}", data)
    return raw


def _local_storage(tmp_path):
    forget_checked()
    return open_storage(None, str(tmp_path), area="runs")


def test_metrics_entries_leave_the_jsonl_for_a_vmx_per_writer(tmp_path):
    raw = _v1_local(tmp_path)
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    rec = "runs/my-app/r1"
    names = {k for k in raw.keys() if k.startswith(rec + "/")}
    assert {f"{rec}/metrics/w1.vmx", f"{rec}/metrics/v1.vmx"} <= names
    assert not any(k.endswith(".vms") for k in names)
    for key in METRIC_KEYS:
        if f"{rec}/{key}" in names:
            lines = raw.get(f"{rec}/{key}").decode().splitlines()
            assert all(json.loads(l)["type"] != "metrics" for l in lines)
    types = [json.loads(l)["type"] for l in raw.get(f"{rec}/log/w1.jsonl").decode().splitlines()]
    assert types == ["create", "params", "rewind"]


def test_every_reader_returns_the_v1_values(tmp_path):
    _v1_local(tmp_path)
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    _assert_readers_match(_local_storage(tmp_path))


def test_file_uri_store_converts_metrics(tmp_path):
    _v1_local(tmp_path)
    assert run_migrate(["--store", f"file://{tmp_path}"]) == 0
    _assert_readers_match(_local_storage(tmp_path))


def test_format_version_1_records_become_2(tmp_path):
    raw = _v1_local(tmp_path, meta_extra={"format_version": 1})
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    meta = yaml.safe_load(raw.get("runs/my-app/r1/metadata.yml"))
    assert meta["format_version"] == 2


def test_metrics_migration_is_idempotent(tmp_path):
    raw = _v1_local(tmp_path)
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    before = {k: raw.get(k) for k in raw.keys()}
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    assert {k: raw.get(k) for k in raw.keys()} == before


def test_a_kill_mid_record_resumes(tmp_path, monkeypatch):
    raw = _v1_local(tmp_path)
    real, calls = migrate_mod._put, []

    def dying(tree, record, key, source):
        if len(calls) == 2:
            raise KeyboardInterrupt
        calls.append(key)
        return real(tree, record, key, source)

    monkeypatch.setattr(migrate_mod, "_put", dying)
    with pytest.raises(KeyboardInterrupt):
        run_migrate(["--dir", str(tmp_path)])
    assert "runs/my-app/r1/metadata.yml" not in raw.keys()
    monkeypatch.undo()
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    _assert_readers_match(_local_storage(tmp_path))


def test_live_runs_keep_their_metrics_entries(tmp_path):
    from migrate_fixtures import live_state

    raw = _v1_local(tmp_path, state=live_state())
    assert run_migrate(["--dir", str(tmp_path), "--skip-live"]) == 0
    old = local_key(("run",), "r1")
    assert raw.get(f"{old}/log.w1.jsonl") == _jsonl(W1)
    assert not any(k.startswith("runs/") for k in raw.keys())


@pytest.fixture
def s3(monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket="bkt")
        yield ObjectRaw(client, "bkt")


def test_s3_store_converts_metrics(s3):
    for name, data in _run_files().items():
        s3.put(f"{object_key(('run',), 'r1', 'team')}/{name}", data)
    assert run_migrate(["--store", "s3://bkt/team"]) == 0
    assert "team/runs/my-app/r1/metrics/w1.vmx" in s3.keys()
    before = {k: s3.get(k) for k in s3.keys()}
    assert run_migrate(["--store", "s3://bkt/team"]) == 0
    assert {k: s3.get(k) for k in s3.keys()} == before
    forget_checked()
    _assert_readers_match(open_storage("s3://bkt/team", None, area="runs"))


def test_log_files_a_compacted_log_supersedes_are_dropped(tmp_path):
    raw = _v1_local(tmp_path)
    old = local_key(("run",), "r1")
    raw.put(f"{old}/log.w1@000000-000001.jsonl", _jsonl(W1 + W1_SEG))
    raw.put(f"{old}/log.w1.jsonl", _jsonl(W1[:3]))
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    logs = {k for k in raw.keys() if k.startswith("runs/my-app/r1/log/")}
    assert logs == {"runs/my-app/r1/log/w1@000000-000001.jsonl"}
    _assert_readers_match(_local_storage(tmp_path))
