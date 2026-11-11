"""``download_model`` of an absolute ``artifact_path`` on the experiment
store's scheme borrows the store's URI settings (an ``s3://`` store's
``endpoint_url``, e.g. MinIO; ``gs://``'s ``endpoint_url``; ``az://``'s
``account_url``); the artifact URI's own query parameters win."""
import boto3
import pytest
from s3_helpers import BUCKET, PREFIX, mocked_bucket

import vmn_exp.storage.s3_base as s3_base
from vmn_exp.sdk.models import download_model, register_model
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.registry import location_local_path, open_store

STORE_ENDPOINT = "http://minio.test:9000"
OTHER_ENDPOINT = "http://other.test:9000"
MODELS = "models-bucket"


@pytest.fixture
def endpoints(monkeypatch):
    """The ``endpoint_url`` of every S3 client built, under a moto that serves
    both custom endpoints."""
    monkeypatch.setenv("MOTO_S3_CUSTOM_ENDPOINTS", f"{STORE_ENDPOINT},{OTHER_ENDPOINT}")
    built = []
    real = s3_base.boto3_client

    def recording(endpoint_url=None, proxies=None):
        built.append(endpoint_url)
        return real(endpoint_url, proxies)

    monkeypatch.setattr(s3_base, "boto3_client", recording)
    with mocked_bucket(monkeypatch):
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket=MODELS)
        s3.put_object(Bucket=MODELS, Key="clf/model.pt", Body=b"minio")
        yield built


def _store(tmp_path):
    """The store a run resolves: the remote fronted by a local root."""
    return open_storage(f"s3://{BUCKET}/{PREFIX}?endpoint_url={STORE_ENDPOINT}",
                        root=str(tmp_path / "local"), area="runs")


def _download(storage, artifact_path):
    register_model("clf", run="0.0.1-dev.aaa", app_name="trainer",
                   artifact_path=artifact_path, storage=storage)
    return download_model("clf@latest", storage=storage, record=False)


def test_an_artifact_on_another_bucket_uses_the_stores_endpoint(tmp_path, endpoints):
    storage = _store(tmp_path)
    endpoints.clear()
    local = _download(storage, f"s3://{MODELS}/clf/model.pt")
    assert open(local, "rb").read() == b"minio"
    assert endpoints == [STORE_ENDPOINT]


def test_the_uris_endpoint_url_overrides_the_stores(tmp_path, endpoints):
    storage = _store(tmp_path)
    endpoints.clear()
    _download(storage, f"s3://{MODELS}/clf/model.pt?endpoint_url={OTHER_ENDPOINT}")
    assert endpoints == [OTHER_ENDPOINT]


@pytest.fixture
def adapters(monkeypatch):
    """``(location, setting)`` of every gs/az client built, through stubs
    that hold no object."""
    import vmn_exp.storage.azure as azure
    import vmn_exp.storage.gcs as gcs

    built = []

    def stub(location, setting):
        built.append((location, setting))
        return object()

    for backend in (gcs, azure):
        monkeypatch.setattr(backend, "_default_adapter", stub)
    return built


@pytest.mark.parametrize("scheme, option", [("gs", "endpoint_url"), ("az", "account_url")])
def test_gcs_and_azure_downloads_use_the_stores_setting(adapters, scheme, option):
    store = open_store(f"{scheme}://store/p?{option}=https://store.test")
    assert location_local_path(f"{scheme}://models/clf.pt", store=store) is None
    location_local_path(f"{scheme}://models/clf.pt?{option}=https://own.test", store=store)
    assert adapters == [("store", "https://store.test"), ("models", "https://store.test"),
                        ("models", "https://own.test")]


def test_another_schemes_store_lends_no_settings(adapters, endpoints):
    store = open_store("gs://store/p?endpoint_url=http://gcs.test")
    assert location_local_path(f"s3://{MODELS}/clf/model.pt", store=store)
    assert endpoints[-1] is None
