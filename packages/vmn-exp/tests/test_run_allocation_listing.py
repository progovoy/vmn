"""Allocating a run of a code version with many runs lists only what can
collide: a writer suffix's own names, and for ``.rN`` nothing at all once
this process knows the code version's highest run."""

import boto3
import pytest
from moto import mock_aws

from vmn_exp.core import run_hint
from vmn_exp.core.writer import allocate_run_verstr
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
    for var in ("VMN_WRITER_ID", "VMN_EXP_OFFLINE"):
        monkeypatch.delenv(var, raising=False)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


@pytest.fixture
def listed():
    """Every ``list_objects_v2`` Prefix any storage of the bucket asks for."""
    calls = []
    real = S3SnapshotStorage.__init__

    def init(self, *args, **kwargs):
        real(self, *args, **kwargs)
        list_objects = self._s3.list_objects_v2

        def spy(**params):
            calls.append(params.get("Prefix"))
            return list_objects(**params)

        self._s3.list_objects_v2 = spy

    S3SnapshotStorage.__init__ = init
    yield calls
    S3SnapshotStorage.__init__ = real


def _storage():
    return S3SnapshotStorage(BUCKET, prefix="exps/runs")


def _record(verstr):
    return {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {}


def _seed(storage, names):
    for verstr in names:
        assert storage.create_exclusive(APP, verstr, _record(verstr)[0], {})


def _allocate(storage, **kwargs):
    return allocate_run_verstr(storage, APP, CODE, make_record=_record, **kwargs)


def test_a_writer_suffix_lists_only_names_under_code_dot_suffix(listed, monkeypatch):
    storage = _storage()
    _seed(storage, [CODE] + [f"{CODE}.r{n}" for n in range(2, 30)] + [f"{CODE}.pod-7"])
    monkeypatch.setenv("VMN_WRITER_ID", "pod-7")
    listed.clear()

    assert _allocate(storage) == f"{CODE}.pod-7.2"

    scope = storage._app_prefix(APP) + f"/{CODE}.pod-7"
    assert listed and all(prefix.startswith(scope) for prefix in listed), listed


def test_an_explicit_suffix_lists_only_its_own_names(listed):
    storage = _storage()
    _seed(storage, [f"{CODE}.r{n}" for n in range(2, 10)])
    listed.clear()

    assert _allocate(storage, suffix="job") == f"{CODE}.job"

    scope = storage._app_prefix(APP) + f"/{CODE}.job"
    assert all(prefix.startswith(scope) for prefix in listed), listed


def _code_listings(listed, storage):
    scope = storage._app_prefix(APP) + f"/{CODE}."
    return [p for p in listed if p == scope]


def test_repeated_rn_allocations_in_one_process_list_once(listed):
    _seed(_storage(), [CODE] + [f"{CODE}.r{n}" for n in range(2, 20)])
    listed.clear()

    # A fresh storage per call, as a launcher opening the store per run does.
    got = [_allocate(_storage(), suffix=None) for _ in range(5)]

    assert got == [f"{CODE}.r{n}" for n in range(20, 25)]
    assert len(_code_listings(listed, _storage())) == 1


def test_rn_allocation_relists_when_another_host_took_the_next_names(listed):
    storage = _storage()
    _seed(storage, [CODE])
    assert _allocate(storage, suffix=None) == f"{CODE}.r2"
    # Another host claims r3..r12 behind this process's back.
    _seed(storage, [f"{CODE}.r{n}" for n in range(3, 13)])
    listed.clear()

    assert _allocate(storage, suffix=None) == f"{CODE}.r13"
    assert len(_code_listings(listed, storage)) == 1


def test_rn_hint_still_takes_a_free_next_name_after_a_few_collisions(listed):
    storage = _storage()
    assert _allocate(storage, suffix=None) == CODE
    _seed(storage, [f"{CODE}.r2"])
    listed.clear()

    assert _allocate(storage, suffix=None) == f"{CODE}.r3"
    assert _code_listings(listed, storage) == []


def test_rn_hint_relists_once_its_highest_run_is_gone(listed):
    storage = _storage()
    _seed(storage, [CODE, f"{CODE}.r2"])
    assert _allocate(storage, suffix=None) == f"{CODE}.r3"
    storage.delete(APP, f"{CODE}.r3")

    assert _allocate(storage, suffix=None) == f"{CODE}.r3"


def test_the_rn_hint_is_per_store_app_and_code(listed):
    a = _storage()
    other = S3SnapshotStorage(BUCKET, prefix="other/runs")
    _seed(a, [CODE, f"{CODE}.r2"])

    assert _allocate(a, suffix=None) == f"{CODE}.r3"
    assert _allocate(other, suffix=None) == CODE
    assert allocate_run_verstr(a, "app2", CODE, make_record=_record, suffix=None) == CODE
    assert allocate_run_verstr(a, APP, "1.0.0-dev.x", make_record=_record,
                               suffix=None) == "1.0.0-dev.x"


@pytest.fixture(autouse=True)
def _fresh_hints():
    run_hint.clear()
    yield
    run_hint.clear()
