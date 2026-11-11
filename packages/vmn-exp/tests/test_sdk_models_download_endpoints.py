"""An absolute ``s3://`` download is cached per endpoint (the same bucket/key
on AWS and on MinIO are different objects), and a configured
``endpoint_url`` reaches it even with no remote store to borrow it from."""
from types import SimpleNamespace

import boto3
import pytest
from s3_helpers import mocked_bucket

import vmn_exp.storage.s3_base as s3_base
from vmn_exp.core.storage_resolve import _get_experiment_storage, resolve_experiment_storage
from vmn_exp.core.writer import STORAGE_ENV, merge_conf_into_params
from vmn_exp.sdk.models import download_model, register_model
from vmn_exp.storage.registry import location_local_path

MINIO = "http://minio.test:9000"
SECRET_MINIO = "http://user:s3cr3t@minio.test:9000"
OTHER = "http://other.test:9000"
MODELS = "models-bucket"
ARTIFACT = f"s3://{MODELS}/clf/model.pt"


@pytest.fixture
def endpoints(monkeypatch):
    """The ``endpoint_url`` of every S3 client built, under a moto that serves
    the custom endpoints."""
    for var in STORAGE_ENV.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("VMN_EXPERIMENT_DIR", raising=False)
    monkeypatch.setenv("MOTO_S3_CUSTOM_ENDPOINTS", f"{MINIO},{OTHER},{SECRET_MINIO}")
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


def test_one_bucket_key_on_two_endpoints_caches_apart(endpoints):
    aws = location_local_path(ARTIFACT)
    minio = location_local_path(f"{ARTIFACT}?endpoint_url={MINIO}")
    other = location_local_path(f"{ARTIFACT}?endpoint_url={OTHER}")
    assert len({aws, minio, other}) == 3
    assert location_local_path(f"{ARTIFACT}?endpoint_url={MINIO}") == minio


def test_the_cache_path_holds_no_endpoint_or_credentials(endpoints):
    path = location_local_path(f"{ARTIFACT}?endpoint_url={SECRET_MINIO}")
    assert open(path, "rb").read() == b"minio"
    assert "s3cr3t" not in path and "minio.test" not in path


def _download(storage):
    register_model("clf", run="0.0.1-dev.aaa", app_name="trainer",
                   artifact_path=ARTIFACT, storage=storage)
    return download_model("clf@latest", storage=storage, record=False)


def test_an_env_endpoint_applies_without_a_remote_store(tmp_path, endpoints, monkeypatch):
    monkeypatch.setenv(STORAGE_ENV["endpoint_url"], MINIO)
    storage = resolve_experiment_storage(dir=str(tmp_path / "local"))
    endpoints.clear()
    assert open(_download(storage), "rb").read() == b"minio"
    assert endpoints == [MINIO]


def test_a_conf_endpoint_applies_without_a_remote_store(tmp_path, endpoints):
    vcs = SimpleNamespace(experiment={"storage": {"endpoint_url": MINIO}},
                          vmn_root_path=str(tmp_path))
    params = {}
    merge_conf_into_params(vcs, params)
    storage = _get_experiment_storage(vcs, params)
    endpoints.clear()
    _download(storage)
    assert endpoints == [MINIO]


def test_the_uris_endpoint_still_wins_over_the_conf(tmp_path, endpoints, monkeypatch):
    monkeypatch.setenv(STORAGE_ENV["endpoint_url"], MINIO)
    storage = resolve_experiment_storage(dir=str(tmp_path / "local"))
    endpoints.clear()
    assert location_local_path(f"{ARTIFACT}?endpoint_url={OTHER}", store=storage)
    assert endpoints == [OTHER]


def test_an_area_of_the_store_keeps_the_endpoint(tmp_path, endpoints, monkeypatch):
    monkeypatch.setenv(STORAGE_ENV["endpoint_url"], MINIO)
    storage = resolve_experiment_storage(dir=str(tmp_path / "local"))
    assert storage.in_area("models").uri_options("s3") == {"endpoint_url": MINIO}
    assert storage.uri_options("gs") == {}
