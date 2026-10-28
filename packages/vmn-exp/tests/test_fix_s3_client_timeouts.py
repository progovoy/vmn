"""vmn's S3 clients bound every call: explicit connect/read timeouts and
adaptive retries, so a stalled connection fails (and is retried) instead of
hanging an index refresh forever (botocore waits 60 s per read by default and
retries legacy-style), and a throttling store (``SlowDown``) slows the client
down instead of failing request after request."""
import pytest

pytest.importorskip("boto3")

from vmn_exp.storage.s3_base import boto3_client, sigv4_client  # noqa: E402


@pytest.fixture(autouse=True)
def _region(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")


@pytest.mark.parametrize("make", [boto3_client, sigv4_client])
def test_the_s3_client_has_explicit_timeouts_and_retries(make):
    config = make().meta.config
    assert 0 < config.connect_timeout <= 15
    assert 0 < config.read_timeout <= 60
    assert config.retries["mode"] == "adaptive"
    assert config.retries["total_max_attempts"] >= 3  # botocore's key for attempts in all


def test_the_pool_size_is_kept():
    from vmn_exp.storage.s3_base import MAX_POOL_CONNECTIONS

    assert boto3_client().meta.config.max_pool_connections == MAX_POOL_CONNECTIONS
