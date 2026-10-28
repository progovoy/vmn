"""Plan 28 T2a over HTTP: ``/metrics`` carries each served app's rollup
gauges — ``vmn_runs``, ``vmn_attention``, per live or recently ended
top-level outer run ``vmn_job_runs``/``vmn_job_progress``/
``vmn_job_eta_seconds``, and ``vmn_index_freshness_seconds`` — with the
numbers ``experiments-status`` and an outer run's ``summary`` serve, read
from what the index last published: a scrape never loads or refreshes one."""
import datetime

import pytest
import yaml
from prometheus_parse import label_sets, parse, value

pytest.importorskip("fastapi")
import vmn_exp.core.status as status_mod
from fastapi.testclient import TestClient
from vmn_exp.core.app_settings_store import write_settings
from vmn_exp.storage.areas import RUNS
from vmn_exp.storage.open import open_storage

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
NOW = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
LABELS = {"workspace": "ws", "app": APP}
GRID = 'grid "a"\\b\nc'
SETTINGS = """\
ui:
  attention:
    - {key: unstable, query: 'tags.health = "unstable"', level: error}
"""


def _v(n):
    return f"0.0.1-dev.abc1234.def5678.r{n}"


def _iso(minutes_ago):
    return (NOW - datetime.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(storage, n, ago, parent=None, state="ok", name=None, health=None):
    meta = {"verstr": _v(n), "timestamp": _iso(ago)}
    if parent is not None:
        meta["parent"] = _v(parent)
    if name is not None:
        meta["name"] = name
    storage.save(APP, _v(n), meta, {})
    if health:
        storage.append_log_entry(APP, _v(n), "w", {"timestamp": "t", "type": "tags",
                                                   "set": {"health": health}})
    ended = {"started_at": _iso(ago), "finished_at": _iso(ago - 1)}
    states = {"ok": dict(ended, state="finished", exit_code=0),
              "failed": dict(ended, state="finished", exit_code=1),
              "live": {"state": "running", "started_at": _iso(ago), "heartbeat": _iso(0),
                       "heartbeat_interval_sec": 30}}
    if state in states:
        storage.save_file(APP, _v(n), "run_state.yml", yaml.dump(states[state]))


def _fleet(storage):
    """Outer r1 live (r2 unstable, r3 failed, r4 waiting); outer r5 ended
    3 h ago (r6); outer r7 ended 30 h ago (r8); single r9 failed."""
    _run(storage, 1, 120, state="live", name=GRID)
    _run(storage, 2, 110, parent=1, health="unstable")
    _run(storage, 3, 100, parent=1, state="failed")
    _run(storage, 4, 90, parent=1, state=None)
    _run(storage, 5, 180, name="old")
    _run(storage, 6, 179, parent=5)
    _run(storage, 7, 30 * 60, name="older")
    _run(storage, 8, 30 * 60 - 1, parent=7)
    _run(storage, 9, 10, state="failed")


class _Clock:
    now = NOW


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or c.now)
    return c


@pytest.fixture
def server(tmp_path, clock):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    _fleet(storage)
    write_settings(storage, APP, SETTINGS)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    return lambda **kw: TestClient(create_app(manager, **kw))


def _status(client):
    r = client.get(f"{BASE}/experiments-status")
    assert r.status_code == 200, r.text
    return r.json()


def _scrape(client):
    r = client.get("/metrics")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    return parse(r.text)


def _outer_runs(samples):
    return {s["outer_run"] for s in label_sets(samples, "vmn_job_runs")}


def test_run_counts_match_experiments_status(server):
    client = server()
    body = _status(client)
    samples = _scrape(client)
    expected = dict(body["counts"], never_started=body["never_started"], lost=body["lost"])
    got = {s["status"]: value(samples, "vmn_runs", **s)
           for s in label_sets(samples, "vmn_runs")}
    assert got == {k: float(n) for k, n in expected.items()}
    assert got["failed"] == 2 and got["running"] == 1
    assert all(set(s) == {"workspace", "app", "status"} for s in label_sets(samples, "vmn_runs"))


def test_attention_counts_match_experiments_status(server):
    client = server()
    body = _status(client)
    samples = _scrape(client)
    (part,) = body["attention"]
    assert value(samples, "vmn_attention", **LABELS, key="unstable") == part["count"] == 1
    assert value(samples, "vmn_attention", **LABELS, key="failed") == body["failed_recent"] == 2
    assert value(samples, "vmn_attention", **LABELS, key="stuck") == body["counts"]["stuck"]
    assert value(samples, "vmn_attention", **LABELS, key="running") == body["counts"]["running"]


def test_live_and_recently_ended_outer_runs_match_their_summaries(server):
    client = server()
    _status(client)
    samples = _scrape(client)
    assert _outer_runs(samples) == {_v(1), _v(5)}
    for n, name in ((1, GRID), (5, "old")):
        summary = client.get(f"{BASE}/experiments/{_v(n)}/summary").json()
        job = dict(LABELS, outer_run=_v(n), name=name)
        counts = dict(summary["counts"], never_started=summary["never_started"],
                      lost=summary["lost"])
        assert {s: value(samples, "vmn_job_runs", **job, status=s) for s in counts} == {
            s: float(c) for s, c in counts.items()}
        assert value(samples, "vmn_job_progress", **job) == summary["progress"]
        assert value(samples, "vmn_job_eta_seconds", **job) == summary["eta_sec"]
    assert value(samples, "vmn_job_runs", **LABELS, outer_run=_v(1), name=GRID,
                 status="waiting") == 1


def test_the_ended_window_is_a_setting(server):
    client = server(metrics_ended_hours=48)
    _status(client)
    assert _outer_runs(_scrape(client)) == {_v(1), _v(5), _v(7)}
    client = server(metrics_ended_hours=1)
    _status(client)
    assert _outer_runs(_scrape(client)) == {_v(1)}


def test_the_outer_run_series_are_capped_live_first(server, monkeypatch):
    from vmn_exp.ui import rollup_gauges

    monkeypatch.setattr(rollup_gauges, "MAX_OUTER_RUNS", 1)
    client = server(metrics_ended_hours=48)
    _status(client)
    assert _outer_runs(_scrape(client)) == {_v(1)}


def test_index_freshness_is_the_age_of_the_last_refresh(server, clock):
    client = server()
    _status(client)
    clock.now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=600)
    age = value(_scrape(client), "vmn_index_freshness_seconds", **LABELS)
    assert age is not None and 600 <= age <= 630


def test_a_scrape_before_any_request_loads_no_index(server, monkeypatch):
    from vmn_exp.ui import index as ui_index

    loads = []
    monkeypatch.setattr(ui_index, "app_snapshot", lambda *a, **k: loads.append(a))
    samples = _scrape(server())
    assert loads == []
    assert {name for name, _ in samples} == {"vmn_cache_drift_total"} or not samples


def test_a_scrape_never_refreshes_an_index(server, monkeypatch):
    from vmn_exp.core.index import ExperimentIndex

    client = server()
    _status(client)

    def refused(*a, **k):
        raise AssertionError("a scrape refreshed the index")

    for name in ("refresh", "reconcile", "refresh_if_stale", "snapshot", "snapshot_now"):
        monkeypatch.setattr(ExperimentIndex, name, refused)
    samples = _scrape(client)
    assert value(samples, "vmn_runs", **LABELS, status="failed") == 2


def test_label_values_are_escaped(server):
    client = server()
    _status(client)
    response = client.get("/metrics").text
    assert 'name="grid \\"a\\"\\\\b\\nc"' in response
    assert len(parse(response)) > 0


def test_an_apps_gauges_are_computed_once_per_snapshot_and_minute(server, clock, monkeypatch):
    from vmn_exp.ui import metrics_feed

    calls = []
    real = metrics_feed.app_samples
    monkeypatch.setattr(metrics_feed, "app_samples", lambda *a: calls.append(1) or real(*a))
    client = server()
    _status(client)
    first = _scrape(client)
    assert _scrape(client) == first and len(calls) == 1
    clock.now = NOW + datetime.timedelta(minutes=1)
    _scrape(client)
    assert len(calls) == 2


def test_the_metrics_route_keeps_its_auth(server):
    client = server(token="sekret")
    assert client.get("/metrics").status_code == 401
    r = client.get("/metrics", headers={"Authorization": "Bearer sekret"})
    assert r.status_code == 200
