"""``get_run_states``: many runs' states in one call, read straight from the
store — no experiment index, no listing of the app's runs."""

import datetime

import boto3
import pytest
import yaml
from moto import mock_aws

import vmn_exp.core.index as experiment_index
import vmn_exp.core.refs as refs
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.sdk import reader, run_states
from vmn_exp.storage.s3 import S3SnapshotStorage

BUCKET = "vmn-bucket"
APP = "app"
CODE = "2.0.251-dev.852cb2d.0000000"
DONE, FAILED, LIVE = f"{CODE}.r2", f"{CODE}.r3", f"{CODE}.r4"
MISSING = f"{CODE}.r9"


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
    # An old heartbeat: only the store's write time can say the run is alive.
    return yaml.dump({"state": state, "exit_code": exit_code, "pid": 1, "host": "h",
                      "heartbeat": "2026-01-01T00:00:00Z", "heartbeat_interval_sec": 30})


@pytest.fixture
def storage():
    s = S3SnapshotStorage(BUCKET, prefix="exps/runs")
    for n, verstr in enumerate((CODE, DONE, FAILED, LIVE)):
        meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{n}Z", "format_version": 2}
        assert s.create_exclusive(APP, verstr, meta, {})
    s.save_file(APP, DONE, RUN_STATE_FILE, _state("finished", 0))
    s.save_file(APP, FAILED, RUN_STATE_FILE, _state("finished", 1))
    s.save_file(APP, LIVE, RUN_STATE_FILE, _state("running"))
    return s


@pytest.fixture
def no_index(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the experiment index was consulted")

    monkeypatch.setattr(experiment_index, "indexed_snapshot", refuse)
    monkeypatch.setattr(refs, "point_view", refuse)
    monkeypatch.setattr(refs, "placement_snapshot", refuse)


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
    app = storage._app_prefix(APP) + "/"
    return [p for p in listed if p is not None and p.startswith(app)
            and "/" not in p[len(app):]]


def test_states_of_exact_verstrs_carry_status_and_store_write_time(storage, no_index):
    states = reader.get_run_states(APP, [DONE, FAILED], storage=storage)

    assert set(states) == {DONE, FAILED}
    done, failed = states[DONE], states[FAILED]
    assert (done["status"], failed["status"]) == ("succeeded", "failed")
    assert done["verstr"] == DONE and failed["verstr"] == FAILED
    assert done["run_state"]["exit_code"] == 0 and done["state"] == "finished"
    assert isinstance(done["observed_at"], datetime.datetime)
    assert done["observed_at"].tzinfo is not None


def test_status_is_derived_with_the_store_write_time(storage, no_index):
    # The heartbeat is stale, but the store wrote run_state.yml just now.
    assert reader.get_run_states(APP, [LIVE], storage=storage)[LIVE]["status"] == "running"


def test_a_missing_run_maps_to_none(storage, no_index):
    states = reader.get_run_states(APP, [MISSING, DONE], storage=storage)

    assert states[MISSING] is None
    assert states[DONE]["status"] == "succeeded"


def test_a_run_that_never_started_is_created(storage, no_index):
    entry = reader.get_run_states(APP, [CODE], storage=storage)[CODE]

    assert entry["status"] == "created"
    assert entry["run_state"] is None
    assert entry["observed_at"] is None
    assert entry["verstr"] == CODE


def test_no_refs_reads_nothing(storage, no_index):
    assert reader.get_run_states(APP, [], storage=storage) == {}


def test_exact_verstrs_list_no_app_runs(storage, listed, no_index):
    reader.get_run_states(APP, [DONE, FAILED, LIVE, MISSING], storage=storage)

    assert _app_listings(storage, listed) == []


def test_runs_are_read_in_one_parallel_fan_out(storage, monkeypatch, no_index):
    batches = []
    real = run_states.parallel_map

    def spy(fn, items):
        batches.append(list(items))
        return real(fn, items)

    monkeypatch.setattr(run_states, "parallel_map", spy)
    reader.get_run_states(APP, [DONE, FAILED, LIVE, DONE], storage=storage)

    assert len(batches) == 1
    assert sorted(batches[0]) == sorted([DONE, FAILED, LIVE])


def test_a_relative_ref_resolves_to_its_run(storage):
    states = reader.get_run_states(APP, ["latest", "@2"], storage=storage)

    assert states["latest"]["verstr"] == LIVE
    assert states["@2"]["verstr"] == DONE


def test_an_unresolvable_relative_ref_maps_to_none(storage):
    assert reader.get_run_states(APP, ["@99"], storage=storage) == {"@99": None}
