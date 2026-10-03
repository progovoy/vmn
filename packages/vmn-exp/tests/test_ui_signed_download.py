"""Per-workspace ``downloads: redirect`` — 302 to a presigned GET (plan 11 §7.2)."""
import os
from urllib.parse import parse_qs, urlparse

import boto3
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from s3_helpers import BUCKET, PREFIX, mocked_bucket  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.storage.uri import s3_uri  # noqa: E402

APP = "my_app"
V = "0.0.1-dev.abc.def"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments/{V}"


def _put(name, body):
    from vmn_exp.storage.s3 import S3SnapshotStorage

    uri = S3SnapshotStorage(BUCKET, prefix=f"{PREFIX}/runs").artifact_uri(APP, V, name)
    key = uri.split(f"s3://{BUCKET}/", 1)[1]
    boto3.client("s3").put_object(Bucket=BUCKET, Key=key, Body=body)
    return key


def _client(tmp_path, downloads):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = s3_uri(BUCKET, PREFIX)
    open_storage(uri, area=RUNS).save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    manager = WorkspaceManager(os.path.join(tmp_path, "ui"))
    manager.add_store("ws", uri, downloads=downloads)
    return TestClient(create_app(manager))


@pytest.fixture
def bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _query(location):
    return parse_qs(urlparse(location).query)


def test_redirect_answers_302_to_a_short_presigned_get(tmp_path, bucket):
    key = _put("artifacts/model.bin", b"weights")
    r = _client(tmp_path, "redirect").get(f"{BASE}/artifacts/model.bin", follow_redirects=False)
    assert r.status_code == 302
    location = r.headers["location"]
    assert urlparse(location).path.endswith(key)
    q = _query(location)
    assert int(q["X-Amz-Expires"][0]) <= 300
    assert "attachment" in q["response-content-disposition"][0]
    assert "model.bin" in q["response-content-disposition"][0]


def test_images_redirect_without_attachment_disposition(tmp_path, bucket):
    _put("outputs/media/img/0.png", b"\x89PNG")
    r = _client(tmp_path, "redirect").get(f"{BASE}/outputs/media/img/0.png",
                                          follow_redirects=False)
    assert r.status_code == 302
    assert "response-content-disposition" not in _query(r.headers["location"])


def test_redirect_of_a_missing_object_is_404(tmp_path, bucket):
    r = _client(tmp_path, "redirect").get(f"{BASE}/artifacts/nope.bin", follow_redirects=False)
    assert r.status_code == 404


def test_stream_mode_serves_the_bytes(tmp_path, bucket):
    _put("artifacts/model.bin", b"weights")
    r = _client(tmp_path, "stream").get(f"{BASE}/artifacts/model.bin", follow_redirects=False)
    assert r.status_code == 200 and r.content == b"weights"
