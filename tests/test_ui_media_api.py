"""The ui API's media: detail indexes, paged tables and PNG downloads."""
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.core.png import encode_png
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import open_storage

APP = "app"
V = "1.0.0-dev.media"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments/{V}"


@pytest.fixture
def storage(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    st = open_storage(vmn_root_path=str(root), subdir="experiments")
    st.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


@pytest.fixture
def run(storage):
    run = Run(storage, APP, V, 60)
    run._open()
    yield run
    run.finish()


@pytest.fixture
def client(tmp_path, storage):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(tmp_path / "repo"))
    return TestClient(create_app(manager))


def _png(tmp_path):
    src = tmp_path / "p.png"
    src.write_bytes(encode_png(b"\x00" * 4, 2, 2, 1))
    return str(src)


def test_detail_carries_the_media_indexes(run, client, tmp_path):
    run.log_image("samples", _png(tmp_path), step=0, caption="first")
    run.log_table("preds", [{"y": 1}], step=0)
    run.log_histogram("w", [1, 2, 3], bins=2)
    run.finish()
    got = client.get(BASE).json()
    assert got["media"]["samples"] == [
        {"step": 0, "path": "media/samples/0.png", "caption": "first",
         "width": 2, "height": 2}
    ]
    assert got["tables"]["preds"][0]["rows"] == 1
    assert got["histograms"]["w"][0]["counts"] == [1, 2]
    assert got["histograms_total"] == {"w": 1}


def _media_steps_once_stored(run, client, name, count):
    """The detail's steps of *name* once *count* of them are stored and logged
    (an image's entry is appended by the background uploader)."""
    deadline = time.monotonic() + 10
    while True:
        run._log_buffer.flush()
        steps = [i["step"] for i in client.get(BASE).json()["media"].get(name, [])]
        if len(steps) >= count or time.monotonic() > deadline:
            return steps
        time.sleep(0.02)


def test_detail_sees_media_logged_after_a_first_poll(run, client, tmp_path):
    run.log_image("s", _png(tmp_path), step=0)
    assert _media_steps_once_stored(run, client, "s", 1) == [0]
    run.log_image("s", _png(tmp_path), step=1)
    assert _media_steps_once_stored(run, client, "s", 2) == [0, 1]


def test_a_run_without_media_has_empty_indexes(run, client):
    run.finish()
    got = client.get(BASE).json()
    assert got["media"] == {} and got["tables"] == {} and got["histograms"] == {}


def test_a_logged_image_downloads_as_png(run, client, tmp_path):
    run.log_image("s", _png(tmp_path))
    run.finish()
    got = client.get(f"{BASE}/artifacts/media/s/0.png")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"


def test_table_endpoint_pages_rows(run, client):
    run.log_table("t", [{"n": i, "s": str(i)} for i in range(10)], step=0)
    run.finish()
    got = client.get(f"{BASE}/table/tables/t/0.json", params={"offset": 2, "limit": 3})
    assert got.status_code == 200
    body = got.json()
    assert body["total"] == 10 and body["offset"] == 2
    assert body["rows"] == [[2, "2"], [3, "3"], [4, "4"]]
    assert body["columns"] == [{"name": "n", "type": "number"}, {"name": "s", "type": "string"}]


def test_table_endpoint_sorts_server_side(run, client):
    run.log_table("t", [{"n": 2}, {"n": 9}, {"n": 5}], step=0)
    run.finish()
    body = client.get(
        f"{BASE}/table/tables/t/0.json", params={"sort": "n", "order": "desc"}
    ).json()
    assert [r[0] for r in body["rows"]] == [9, 5, 2]


def test_table_endpoint_errors(run, client, tmp_path):
    run.log_table("t", [{"n": 1}], step=0)
    run.log_image("s", _png(tmp_path))
    run.finish()
    assert client.get(f"{BASE}/table/tables/t/9.json").status_code == 404
    assert client.get(f"{BASE}/table/media/s/0.png").status_code == 400
    assert client.get(f"{BASE}/table/tables/t/0.json", params={"sort": "x"}).status_code == 400
    assert client.get(f"{BASE}/table/a/%2E%2E/b.json").status_code in (400, 404)
    unsafe = BASE.replace(f"/experiments/{V}", "/experiments/a%5Cb")
    assert client.get(f"{unsafe}/table/tables/t/0.json").status_code == 400


def test_streamed_artifacts_get_a_guessed_content_type():
    from vmn_exp.ui.http_params import media_type

    assert media_type("media/s/0.png") == "image/png"
    assert media_type("model.weird_ext") == "application/octet-stream"
