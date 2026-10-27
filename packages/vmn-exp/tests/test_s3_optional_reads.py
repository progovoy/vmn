"""On S3 an object the code already knows is absent is never asked for: a
writer's first log append, a run detail's ``env.yml`` for a run that
captured no environment."""
import json

import pytest
import yaml

moto = pytest.importorskip("moto")
import boto3  # noqa: E402

from vmn_exp.storage import s3_stats  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402
from vmn_exp.ui.readers import experiments as exp_reader  # noqa: E402

APP, V = "app", "1.0.0-dev.a"
BUCKET = "vmn-bucket"
MISSING = ("NoSuchKey", "404", "NotFound")


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield S3SnapshotStorage(BUCKET, prefix="vmn/runs")


@pytest.fixture
def calls():
    seen = []
    s3_stats.add_listener(seen.append)
    yield seen
    s3_stats.remove_listener(seen.append)


def _misses(calls):
    return [c for c in calls if c.error in MISSING]


def _run(storage, env=None):
    meta = {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}
    if env is not None:
        meta["env"] = {"python": env["python"]}
    storage.save(APP, V, meta, {})
    if env is not None:
        storage.save_file(APP, V, "env.yml", yaml.dump(env))
    storage.append_log_entry(APP, V, "w", {"type": "create", "timestamp": meta["timestamp"]})


def test_a_writers_first_append_reads_nothing_back(storage, calls):
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    calls.clear()

    storage.append_log_entry(APP, V, "w", {"type": "note", "timestamp": "t"})

    assert _misses(calls) == []
    body = storage.load_file(APP, V, "log/w.jsonl")
    assert json.loads(body)["type"] == "note"


def test_a_second_append_still_extends_the_object(storage):
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    storage.append_log_entry(APP, V, "w", {"type": "note", "n": 1})
    storage.append_log_entry(APP, V, "w", {"type": "note", "n": 2})

    lines = storage.load_file(APP, V, "log/w.jsonl").decode().splitlines()
    assert [json.loads(line)["n"] for line in lines] == [1, 2]


def test_a_polled_detail_of_a_run_without_env_misses_env_once(storage, calls):
    """No env summary in the metadata: env.yml is most likely absent (only a
    record written by hand has one without it), so one miss is remembered."""
    _run(storage)
    calls.clear()

    for _ in range(3):
        detail, err = exp_reader.get_experiment_from_storage(storage, APP, V)
        assert err is None and detail["env"] is None

    assert len([c for c in calls if c.key.endswith("env.yml")]) <= 1


def test_the_detail_of_a_run_with_env_serves_the_env_file(storage):
    _run(storage, env={"python": "3.12", "packages": {"numpy": "2.0"}})

    detail, err = exp_reader.get_experiment_from_storage(storage, APP, V)

    assert err is None
    assert detail["env"] == {"python": "3.12", "packages": {"numpy": "2.0"}}
