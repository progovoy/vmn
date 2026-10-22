"""``vmn_exp.sdk.create_run(run_id=...)``: register a run under an exact name
with one exclusive create, never a listing of the code version's runs."""

import boto3
import pytest
from moto import mock_aws

from vmn_exp.core.writer import create_run as core_create_run
from vmn_exp.sdk import RunExistsError, create_run
from vmn_exp.storage.s3 import S3SnapshotStorage

BUCKET = "vmn-bucket"
APP = "app"
CODE = "2.0.251-dev.852cb2d.0000000"


@pytest.fixture(autouse=True)
def _s3(monkeypatch):
    for k, v in dict(
        AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x", AWS_DEFAULT_REGION="us-east-1"
    ).items():
        monkeypatch.setenv(k, v)
    for var in ("VMN_WRITER_ID", "VMN_EXP_OFFLINE", "VMN_EXPERIMENT_DIR",
                "VMN_EXPERIMENT_ID"):
        monkeypatch.delenv(var, raising=False)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


@pytest.fixture
def snapshot_meta(tmp_path, monkeypatch):
    path = tmp_path / "vmn_metadata.yml"
    path.write_text(
        f"verstr: {CODE}\napp_name: {APP}\n"
        "base_version: 2.0.251\nbase_commit: 852cb2d\nbranch: master\n"
    )
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(path))
    monkeypatch.chdir(tmp_path)
    return str(path)


def _storage_with_listing_spy():
    storage = S3SnapshotStorage(BUCKET, prefix="exps/runs")
    listed = []
    real = storage._s3.list_objects_v2

    def spy(**params):
        listed.append(params.get("Prefix"))
        return real(**params)

    storage._s3.list_objects_v2 = spy
    return storage, listed


def _seed_runs(storage, count):
    for n in range(2, count + 2):
        verstr = f"{CODE}.r{n}"
        assert storage.create_exclusive(APP, verstr, {"verstr": verstr}, {})


def test_create_run_with_run_id_claims_exactly_that_name_without_listing(snapshot_meta):
    storage, listed = _storage_with_listing_spy()
    _seed_runs(storage, 5)
    listed.clear()
    run_id = f"{CODE}.job-17"

    assert create_run(APP, run_id=run_id, storage=storage, capture_env=False) == run_id

    meta = storage.load_metadata(APP, run_id)
    assert meta["verstr"] == run_id and meta["code_verstr"] == CODE
    record = storage._record_prefix(APP, run_id) + "/"
    assert all(prefix.startswith(record) for prefix in listed), listed


def test_create_run_with_a_taken_run_id_raises_and_keeps_the_existing_record(snapshot_meta):
    storage, _ = _storage_with_listing_spy()
    run_id = f"{CODE}.job-17"
    create_run(APP, run_id=run_id, storage=storage, note="first", capture_env=False)

    with pytest.raises(RunExistsError, match="job-17"):
        create_run(APP, run_id=run_id, storage=storage, note="second", capture_env=False)

    assert storage.load_metadata(APP, run_id)["note"] == "first"


@pytest.mark.parametrize("run_id", [
    "9.9.9-dev.other.0000000.job-1",  # another code version
    CODE,                             # no suffix
    CODE + ".",                       # empty suffix
    CODE + "./../x",                  # not a record name
])
def test_create_run_refuses_a_run_id_that_is_not_a_run_of_its_code(snapshot_meta, run_id):
    storage, _ = _storage_with_listing_spy()

    with pytest.raises(ValueError, match="run_id"):
        create_run(APP, run_id=run_id, storage=storage, capture_env=False)

    assert storage.list_verstrs(APP) == []


def test_core_create_run_takes_the_exact_run_id(snapshot_meta):
    storage, listed = _storage_with_listing_spy()
    run_id = f"{CODE}.pod-3"

    got = core_create_run(storage, APP, CODE, {"timestamp": "t"}, {}, run_id=run_id)

    assert got == run_id
    assert storage.load_metadata(APP, run_id)["code_verstr"] == CODE
    with pytest.raises(RunExistsError):
        core_create_run(storage, APP, CODE, {"timestamp": "t"}, {}, run_id=run_id)
