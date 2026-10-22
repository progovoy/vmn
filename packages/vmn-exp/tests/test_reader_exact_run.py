"""Reading one run by its exact name on a host with no persisted index reads
that run (and its subtree's markers), never a listing of the app's runs."""

import boto3
import pytest
import yaml
from moto import mock_aws

from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.sdk import reader
from vmn_exp.storage.s3 import S3SnapshotStorage

BUCKET = "vmn-bucket"
APP = "app"
CODE = "2.0.251-dev.852cb2d.0000000"
OUTER, INNER = f"{CODE}.r2", f"{CODE}.r3"


@pytest.fixture(autouse=True)
def _s3(monkeypatch, tmp_path):
    for k, v in dict(
        AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x", AWS_DEFAULT_REGION="us-east-1",
        VMN_EXP_CACHE_DIR=str(tmp_path / "cache"),
    ).items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def _state(state, exit_code=None):
    return yaml.dump({"state": state, "exit_code": exit_code, "pid": 1, "host": "h",
                      "heartbeat": "2026-01-01T00:00:00Z", "heartbeat_interval_sec": 30})


@pytest.fixture
def storage():
    s = S3SnapshotStorage(BUCKET, prefix="exps/runs")
    for verstr, parent in ((CODE, None), (OUTER, None), (INNER, OUTER)):
        meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{len(verstr) % 10}Z",
                "format_version": 2, **({"parent": parent} if parent else {})}
        assert s.create_exclusive(APP, verstr, meta, {})
    s.mark_child(APP, OUTER, INNER)
    s.save_file(APP, OUTER, RUN_STATE_FILE, _state("finished", 0))
    s.save_file(APP, INNER, RUN_STATE_FILE, _state("finished", 1))
    return s


@pytest.fixture
def listed(storage):
    calls = []
    real = storage._s3.list_objects_v2

    def spy(**params):
        calls.append(params.get("Prefix"))
        return real(**params)

    storage._s3.list_objects_v2 = spy
    return calls


def _app_listings(storage, listed):
    """Listings of the app's record names (``app/`` or ``app/<name prefix>``),
    not of one record's own objects (``app/<verstr>/...``)."""
    app = storage._app_prefix(APP) + "/"
    return [p for p in listed if p is not None and p.startswith(app)
            and "/" not in p[len(app):]]


def test_get_run_of_an_exact_name_lists_no_app_runs(storage, listed):
    run = reader.get_run(APP, OUTER, storage=storage)

    assert run["verstr"] == OUTER
    assert run["status"] == "succeeded"
    assert run["tree_status"] == "failed"
    assert run["children"] == [INNER]
    assert _app_listings(storage, listed) == []


def test_get_run_of_an_inner_run_knows_its_parent(storage, listed):
    run = reader.get_run(APP, INNER, storage=storage)

    assert run["parent"] == OUTER
    assert run["status"] == "failed"
    assert run["depth"] == 1
    assert _app_listings(storage, listed) == []


def test_get_run_state_reads_one_run(storage, listed):
    state = reader.get_run_state(APP, INNER, storage=storage)

    assert state["status"] == "failed"
    assert state["state"] == "finished"
    assert state["exit_code"] == 1
    assert _app_listings(storage, listed) == []


def test_get_run_state_of_a_run_that_never_started(storage):
    assert reader.get_run_state(APP, CODE, storage=storage)["status"] == "created"


def test_get_run_state_of_a_missing_run_raises(storage):
    with pytest.raises(ValueError):
        reader.get_run_state(APP, f"{CODE}.r9", storage=storage)
