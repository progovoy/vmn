"""``.../experiments-importance``: parameter importance over the filtered runs."""
import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.log import experiment_row
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui import routes_leaderboard

APP = "app"
URL = f"/api/v1/workspaces/ws/apps/{APP}/experiments-importance"


def _row(i, loss, **params):
    ts = f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z"
    log = [
        {"timestamp": ts, "type": "create", "params": params},
        {"timestamp": ts, "type": "metrics", "values": {"loss": loss}},
    ]
    return experiment_row(i + 1, {"verstr": f"1.0.0-dev.r{i:04d}", "timestamp": ts}, log)


@pytest.fixture
def client():
    rows = []
    for i in range(60):
        lr = (i * 7 % 60) / 60
        rows.append(_row(i, 2 * lr + (i % 3) * 0.01, lr=lr, seed=i % 5,
                         model="a" if i < 30 else "b", const=1))
    snap = IndexSnapshot.build(APP, 1, rows, {})
    app = FastAPI()
    routes_leaderboard.register(app, "/api/v1", lambda ws, tag: (snap, {}), lb.LeaderboardCache())
    return TestClient(app)


def test_importance_ranks_params_for_the_metric(client):
    r = client.get(f"{URL}?metric=loss")
    assert r.status_code == 200
    body = r.json()
    assert [entry["param"] for entry in body][0] == "lr"
    assert {entry["param"] for entry in body} == {"lr", "seed", "model"}
    first = body[0]
    assert set(first) == {"param", "importance", "correlation", "spearman", "kind", "n"}
    assert first["kind"] == "numeric" and first["n"] == 60
    assert first["correlation"] > 0.9


def test_the_query_filters_the_runs(client):
    body = client.get(f"{URL}?metric=loss&q=params.model%20%3D%20%22a%22").json()
    assert {entry["param"] for entry in body} == {"lr", "seed"}
    assert body[0]["n"] == 30


def test_a_matching_etag_answers_304(client):
    first = client.get(f"{URL}?metric=loss")
    again = client.get(f"{URL}?metric=loss", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    other = client.get(f"{URL}?metric=loss&q=params.lr%20%3E%200",
                       headers={"If-None-Match": first.headers["etag"]})
    assert other.status_code == 200


def test_unknown_or_missing_metric_and_bad_query_answer_400(client):
    assert client.get(f"{URL}?metric=nope").status_code == 400
    assert client.get(URL).status_code in (400, 422)
    assert client.get(f"{URL}?metric=loss&q=metrics.loss%20%3C").status_code == 400


def test_a_query_matching_nothing_is_an_empty_list(client):
    body = client.get(f"{URL}?metric=loss&q=params.lr%20%3E%2010").json()
    assert body == []


def test_importance_is_memoized_per_snapshot():
    rows = [_row(i, i / 10, lr=i, other=i % 2) for i in range(20)]
    snap = IndexSnapshot.build(APP, 1, rows, {})
    cache = lb.LeaderboardCache()
    first = cache.importance(snap, {}, metric="loss")
    assert cache.importance(snap, {}, metric="loss") is first
