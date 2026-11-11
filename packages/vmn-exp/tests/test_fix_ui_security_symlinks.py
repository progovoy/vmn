"""No read route of the server shows a file a run's record dir only links to.

Anyone who can write into a shared file:// store can replace a record file
with a symlink to a file the server user can read. Each case swaps one record
file for a link to an outside copy whose placeholder became a marker (same
length, so listed sizes still match), then requests every read route of the
run and asserts the marker is in no response.
"""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.core.output_log import OUTPUT_LOG_PATH
from vmn_exp.sdk.run import Run
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.core.real_io import real_io

APP = "app"
V = "1.0.0-dev.sym"
PLACEHOLDER = b"PLACEHOLDER0"
MARKER = b"SECRETMARKER"
ARTIFACT = "artifacts/note.txt"
TABLE = "outputs/tables/t/0.json"
RUN = f"/api/v1/workspaces/ws/apps/{APP}/experiments/{V}"
APP_BASE = f"/api/v1/workspaces/ws/apps/{APP}"


def _record(store_dir, tmp_path):
    storage = LocalSnapshotStorage(str(store_dir), area="runs")
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z",
                          "note": PLACEHOLDER.decode()}, {})
    run = Run(storage, APP, V, 60)
    run._open()
    run.log_metrics({"k_PLACEHOLDER0": 1.0}, step=0)
    run.log_histogram("h_PLACEHOLDER0", {"bins": [0, 1], "counts": [3]}, step=0)
    run.log_table("t", [[PLACEHOLDER.decode(), 1]], columns=["a", "b"])
    src = tmp_path / "note.txt"
    src.write_bytes(b"text " + PLACEHOLDER)
    run.log_artifact(str(src))
    storage.save_file(APP, V, OUTPUT_LOG_PATH, b"line " + PLACEHOLDER + b"\n")
    run.finish(exit_code=1)
    return storage._snapshot_dir(APP, V)


def _log_segment(record_dir):
    return "log/" + os.listdir(os.path.join(record_dir, "log"))[0]


def _link_out(record_dir, name, outside):
    """Replace record file *name* with a link to an outside, marked copy."""
    path = os.path.join(record_dir, *name.split("/"))
    with open(path, "rb") as f:
        data = f.read()
    assert PLACEHOLDER in data, name
    target = outside / name.replace("/", "_")
    target.write_bytes(data.replace(PLACEHOLDER, MARKER))
    os.remove(path)
    os.symlink(str(target), path)


def _client(tmp_path, store_dir):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", f"file://{os.path.abspath(store_dir)}")
    return TestClient(create_app(manager, io=real_io()))


GETS = [
    f"{APP_BASE}/experiments",
    f"{APP_BASE}/experiments-columns",
    f"{APP_BASE}/experiments-facets",
    f"{APP_BASE}/versions",
    f"{APP_BASE}/experiments-diff?v={V}&to={V}",
    RUN,
    f"{RUN}?include_log=true",
    f"{RUN}/log",
    f"{RUN}/metric-keys",
    f"{RUN}/histograms/h_PLACEHOLDER0",
    f"{RUN}/table/{TABLE}",
    f"{RUN}/{ARTIFACT}",
    f"{RUN}/{TABLE}",
    f"{RUN}/{OUTPUT_LOG_PATH}",
    f"{RUN}/baseline",
    f"{RUN}/baselines",
    f"{RUN}/patch",
    f"{RUN}/lineage",
    f"{RUN}/sweep",
    f"{RUN}/summary",
    f"{RUN}/failures",
]
SERIES_BODY = {"verstrs": [V]}


def _bodies(client):
    for url in GETS:
        yield url, client.get(url).content
    yield "series", client.post(f"{APP_BASE}/series", json=SERIES_BODY).content


@pytest.mark.parametrize("kind", [
    "metadata.yml", "log_segment", OUTPUT_LOG_PATH, TABLE, ARTIFACT,
])
def test_no_read_route_serves_a_symlink_target_outside_the_record_dir(tmp_path, kind):
    store_dir, outside = tmp_path / "store", tmp_path / "outside"
    outside.mkdir()
    record_dir = _record(store_dir, tmp_path)
    name = _log_segment(record_dir) if kind == "log_segment" else kind
    _link_out(record_dir, name, outside)
    client = _client(tmp_path, store_dir)

    leaked = [url for url, body in _bodies(client) if MARKER in body]

    assert leaked == []


def test_artifact_listing_omits_symlinks_leaving_the_record_dir(tmp_path):
    store_dir, outside = tmp_path / "store", tmp_path / "outside"
    outside.mkdir()
    record_dir = _record(store_dir, tmp_path)
    _link_out(record_dir, ARTIFACT, outside)

    listed = _client(tmp_path, store_dir).get(RUN).json()["artifacts"]

    assert ARTIFACT not in [a["name"] for a in listed]
    assert TABLE in [a["name"] for a in listed]
