"""The ui API's histograms: names + totals in the detail, steps per name."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.core.media import MAX_HISTOGRAM_STEPS
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import open_storage
from vmn_exp.ui.readers.histograms import INLINE_HISTOGRAM_ITEMS
from vmn_exp.storage.areas import local_store_root

APP = "app"
V = "1.0.0-dev.hist"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments/{V}"


@pytest.fixture
def storage(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    st = open_storage(root=local_store_root(str(root)), area="runs")
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


def _log_many(run, names, steps):
    for step in range(steps):
        for name in names:
            run.log_histogram(name, {"bins": [0, 1], "counts": [step]}, step=step)
    run.finish()


def test_many_key_detail_carries_names_and_totals_only(run, client):
    names = [f"gradients/layer{i}.weight" for i in range(4)]
    steps = INLINE_HISTOGRAM_ITEMS // 2
    _log_many(run, names, steps)
    got = client.get(BASE).json()
    assert got["histograms"] == {}
    assert got["histograms_total"] == {n: steps for n in names}


def test_histogram_endpoint_serves_one_names_steps(run, client):
    _log_many(run, ["gradients/fc.weight", "other"], 3)
    got = client.get(f"{BASE}/histograms/gradients/fc.weight")
    assert got.status_code == 200
    body = got.json()
    assert body["name"] == "gradients/fc.weight" and body["total"] == 3
    assert [s["step"] for s in body["steps"]] == [0, 1, 2]
    assert body["steps"][2] == {"step": 2, "bins": [0.0, 1.0], "counts": [2]}


def test_histogram_endpoint_serves_thinned_steps(run, client):
    _log_many(run, ["h"], MAX_HISTOGRAM_STEPS * 2)
    body = client.get(f"{BASE}/histograms/h").json()
    assert body["total"] == MAX_HISTOGRAM_STEPS * 2
    assert len(body["steps"]) == MAX_HISTOGRAM_STEPS


def test_histogram_endpoint_answers_etag_304(run, client):
    _log_many(run, ["h"], 2)
    first = client.get(f"{BASE}/histograms/h")
    again = client.get(f"{BASE}/histograms/h", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


def test_histogram_endpoint_errors(run, client):
    _log_many(run, ["h"], 1)
    assert client.get(f"{BASE}/histograms/missing").status_code == 404
    gone = BASE.replace(V, "1.0.0-dev.gone")
    assert client.get(f"{gone}/histograms/h").status_code == 404
    unsafe = BASE.replace(f"/experiments/{V}", "/experiments/a%5Cb")
    assert client.get(f"{unsafe}/histograms/h").status_code == 400
