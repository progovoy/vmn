"""Registry reads on S3 find models and versions from the registry's listing:
no HEAD per model or version, and no GET of a file a record does not hold."""
import pytest

moto = pytest.importorskip("moto")
import boto3  # noqa: E402

from vmn_exp.registry.lineage import RegistryLinks  # noqa: E402
from vmn_exp.registry.log import set_alias  # noqa: E402
from vmn_exp.registry.store import (  # noqa: E402
    ensure_model,
    get_version,
    list_models,
    list_versions,
    register_version,
)
from vmn_exp.registry.view import model_state, models_for_run, run_models  # noqa: E402
from vmn_exp.storage import s3_stats  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402
from vmn_exp.ui.readers.models import list_models_response, model_detail_response  # noqa: E402

BUCKET = "vmn-bucket"
APP = "app"
MISSING = ("NoSuchKey", "404", "NotFound")
MODELS = 3


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def _storage():
    return S3SnapshotStorage(BUCKET, prefix="vmn/runs")


@pytest.fixture
def calls():
    seen = []
    s3_stats.add_listener(seen.append)
    yield seen
    s3_stats.remove_listener(seen.append)


@pytest.fixture
def registry(s3):
    storage = _storage()
    for m in range(MODELS):
        name = f"model{m}"
        ensure_model(storage, name, description=f"d{m}")
        for v in range(2):
            register_version(storage, name, run_ref={"app": APP, "verstr": f"0.0.1-dev.r{m}{v}"},
                             artifact_path="model.pt")
        set_alias(storage, name, "prod", 1)
    return storage


def _heads_and_misses(calls):
    return [c for c in calls if c.operation == "HeadObject" or c.error in MISSING]


def test_listing_models_and_versions_heads_nothing(registry, calls):
    storage = _storage()
    calls.clear()

    assert list_models(storage) == [f"model{m}" for m in range(MODELS)]
    assert list_models(storage, kind="model") == [f"model{m}" for m in range(MODELS)]
    assert list_models(storage, kind="dataset") == []
    assert list_versions(storage, "model0") == [1, 2]

    assert _heads_and_misses(calls) == []


def test_reading_a_version_or_a_model_misses_nothing(registry, calls):
    storage = _storage()
    calls.clear()

    assert get_version(storage, "model1", 2)["artifact_path"] == "model.pt"
    assert [v["n"] for v in model_state(storage, "model1")["versions"]] == [1, 2]

    assert _heads_and_misses(calls) == []


def test_run_models_heads_nothing_and_misses_nothing(registry, calls):
    storage = _storage()
    calls.clear()

    found = run_models(storage)
    assert models_for_run(storage, APP, "0.0.1-dev.r10")[0]["aliases"] == ["prod"]

    assert len(found) == 2 * MODELS
    assert _heads_and_misses(calls) == []


def test_the_models_pages_head_nothing_and_miss_nothing(registry, calls):
    storage = _storage()
    calls.clear()

    rows = list_models_response(storage)["models"]
    detail, err = model_detail_response(storage, "model2")

    assert [r["latest_version"] for r in rows] == [2] * MODELS
    assert err is None and [v["version"] for v in detail["versions"]] == [1, 2]
    assert _heads_and_misses(calls) == []


def test_a_version_not_listed_is_not_live_without_a_read(registry, calls):
    links = RegistryLinks(_storage())
    assert links.version_live("model0", 1)
    calls.clear()

    assert not links.version_live("model0", 9)
    assert not links.version_live("nosuch", 1)

    assert _heads_and_misses(calls) == []


def test_an_empty_registry_is_cached_like_any_other(s3, calls):
    storage = _storage()
    assert run_models(storage) == {}
    calls.clear()

    assert run_models(storage) == {}

    assert len(calls) == 1  # the registry listing, no rescan
