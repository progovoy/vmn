"""What the SDK's S3 backend must keep while it is rebuilt on core's
``version_stamp.store.s3_*`` (plan 37 P5c): its format gate (records of a
newer format are skipped), the format version it writes (2, not core's 1),
the children flag its listings note, and which classes define its record
API (R3: a core base must not shadow a format-gated SDK method)."""
import pytest
import yaml
from s3_helpers import BUCKET, PREFIX, mocked_bucket, put_raw, s3_storage

import boto3

from vmn_exp.core.writer import create_run
from vmn_exp.storage import children_flag
from vmn_exp.storage.azure import AzureSnapshotStorage
from vmn_exp.storage.gcs import GCSSnapshotStorage
from vmn_exp.storage.s3 import S3SnapshotStorage

APP = "my_app"
CODE = "0.0.1-dev.abc.def"


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield s3_storage()


def _metadata_of(verstr):
    key = f"{PREFIX}/runs/{APP}/{verstr.replace('+', '_plus_')}/metadata.yml"
    body = boto3.client("s3").get_object(Bucket=BUCKET, Key=key)["Body"].read()
    return yaml.safe_load(body)


def _raw_record(verstr, **fields):
    metadata = dict({"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, **fields)
    put_raw(f"{PREFIX}/runs/{APP}/{verstr}/metadata.yml", yaml.dump(metadata))


# -- the format gate -----------------------------------------------------------


def test_load_metadata_skips_a_record_of_a_newer_format(s3):
    _raw_record("0.0.1", format_version=99)

    assert s3.load_metadata(APP, "0.0.1") is None


def test_list_snapshots_skips_a_record_of_a_newer_format(s3):
    _raw_record("0.0.1", format_version=99)
    _raw_record("0.0.2", format_version=2)

    assert [m["verstr"] for m in s3.list_snapshots(APP)] == ["0.0.2"]


def test_a_newer_format_record_is_still_listed_by_name(s3):
    _raw_record("0.0.1", format_version=99)

    assert s3.list_verstrs(APP) == ["0.0.1"]
    assert s3.exists(APP, "0.0.1")


# -- the format written --------------------------------------------------------


def test_a_saved_snapshot_carries_format_version_2(s3):
    s3.save(APP, "0.0.1", {"verstr": "0.0.1", "timestamp": "t"},
            {"working_tree": "d"})

    assert _metadata_of("0.0.1")["format_version"] == 2


def test_a_created_run_carries_format_version_2(s3):
    verstr = create_run(s3, APP, CODE, {"timestamp": "2026-01-01T00:00:00Z"}, {})

    assert _metadata_of(verstr)["format_version"] == 2


def test_an_exclusive_create_carries_format_version_2(s3):
    assert s3.create_exclusive(APP, "0.0.1", {"verstr": "0.0.1"}, {})

    assert _metadata_of("0.0.1")["format_version"] == 2


def test_a_metadata_update_keeps_format_version_2(s3):
    s3.save(APP, "0.0.1", {"verstr": "0.0.1"}, {})

    assert s3.update_note(APP, "0.0.1", "hello")
    assert _metadata_of("0.0.1") == {"verstr": "0.0.1", "format_version": 2, "note": "hello"}


def test_a_record_s_own_format_version_is_kept(s3):
    s3.save(APP, "0.0.1", {"verstr": "0.0.1", "format_version": 1}, {})

    assert _metadata_of("0.0.1")["format_version"] == 1


def test_a_round_trip_reads_back_metadata_and_patches(s3):
    patches = {
        "working_tree": "d",
        "untracked_files": b"\x1f\x8b",
        "deps": {"lib": {"local_commits": "x"}},
    }
    s3.save(APP, "0.0.1", {"verstr": "0.0.1"}, patches)

    metadata, loaded = s3.load_record(APP, "0.0.1")

    assert metadata == {"verstr": "0.0.1", "format_version": 2}
    assert loaded == patches


# -- the children flag ---------------------------------------------------------


@pytest.mark.parametrize("list_app", ["list_verstrs", "list_record_names", "list_snapshots"])
def test_a_listing_still_notes_the_children_flag(s3, list_app):
    create_run(s3, APP, CODE, {"timestamp": "2026-01-01T00:00:00Z"}, {})
    s3.set_children_complete(APP, True)
    children_flag._SEEN.clear()
    fresh = s3_storage()

    getattr(fresh, list_app)(APP)

    assert fresh.children_flag_seen(APP) == (True, s3.children_flag(APP))


# -- which class defines the record API (R3) -----------------------------------

SDK_BASE = "vmn_exp.storage.base.SnapshotStorage"
SDK_LISTING = "vmn_exp.storage.s3_listing.S3Listing"
SDK_S3 = "vmn_exp.storage.s3.S3SnapshotStorage"
DEFINED_BY = {
    "load_metadata": SDK_BASE,
    "readable": SDK_BASE,
    "load": SDK_BASE,
    "list_snapshots": SDK_LISTING,
    "list_verstrs": SDK_LISTING,
    "list_record_names": SDK_LISTING,
    "exists": SDK_S3,
    "load_record": SDK_S3,
    "load_file": SDK_S3,
}
STORES = (S3SnapshotStorage, GCSSnapshotStorage, AzureSnapshotStorage)


def _defining_class(cls, name):
    owner = next(c for c in cls.__mro__ if name in vars(c))
    return f"{owner.__module__}.{owner.__qualname__}"


@pytest.mark.parametrize("cls", STORES, ids=lambda c: c.__name__)
@pytest.mark.parametrize("name", sorted(DEFINED_BY))
def test_the_record_api_is_defined_where_it_was(cls, name):
    assert _defining_class(cls, name) == DEFINED_BY[name]


@pytest.mark.parametrize("cls", STORES, ids=lambda c: c.__name__)
def test_the_sdk_halves_keep_their_order(cls):
    names = [c.__qualname__ for c in cls.__mro__]
    halves = ["S3SnapshotStorage", "S3Children", "S3ChildrenFlag", "S3Listing",
              "S3Records", "S3Logs", "S3Metrics", "S3Base", "SnapshotStorage"]
    assert [n for n in names if n in halves] == halves
    assert names.index("S3Base") < names.index("SnapshotStorage")


@pytest.mark.parametrize("cls", STORES, ids=lambda c: c.__name__)
@pytest.mark.parametrize("name", ["save", "create_exclusive", "delete",
                                  "update_metadata", "update_note"])
def test_record_writes_resolve_to_the_records_half(cls, name):
    """S3Records (or a base of it alone) — never a class after it."""
    owner = next(c for c in cls.__mro__ if name in vars(c))
    from vmn_exp.storage.s3_records import S3Records

    assert owner in S3Records.__mro__ and owner is not object
