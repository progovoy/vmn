"""Plan 28 P2 + A0: an app's ``ui.progress`` settings name the metrics an
outer run's declared progress is read from; the rollups follow a settings
change at once (the settings are part of their memo keys)."""
import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core.app_settings import SettingsError, parse_settings  # noqa: E402
from vmn_exp.core.app_settings_store import write_settings  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
MAPPING = "ui: {progress: {done: dates_done, total: dates_total, unit: dates}}\n"


def _run(storage, n, metrics=None, parent=None, state="state: finished\nexit_code: 0\n"):
    verstr = f"0.0.1-dev.abc1234.def5678.r{n}"
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{n:02d}Z"}
    if parent is not None:
        meta["parent"] = parent
    storage.save(APP, verstr, meta, {})
    if metrics:
        storage.append_log_entry(APP, verstr, "w",
                                 {"type": "metrics", "values": metrics, "timestamp": "t"})
    storage.save_file(APP, verstr, "run_state.yml", state)
    return verstr


@pytest.fixture
def store(tmp_path):
    """``(client, runs storage, outer run)``: an outer run declaring 20 of 60
    dates under its own names, with three finished children."""
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    outer = _run(storage, 1, {"dates_done": 20, "dates_total": 60})
    for n in (2, 3, 4):
        _run(storage, n, {"loss": float(n)}, parent=outer)
    return TestClient(create_app(manager)), storage, outer


def _summary(client, outer):
    r = client.get(f"{BASE}/experiments/{outer}/summary")
    assert r.status_code == 200, r.text
    return r.json()


def _jobs_row(client):
    (row,) = client.get(f"{BASE}/experiments", params={"top": "jobs", "limit": 50}).json()["rows"]
    return row["job"]


def test_a_progress_mapping_is_validated():
    assert parse_settings(MAPPING)["ui"]["progress"]["unit"] == "dates"
    assert parse_settings("ui: {progress: {done: trials}}\n")
    for bad in ("ui: {progress: 3}\n", "ui: {progress: {done: ''}}\n",
                "ui: {progress: {done: 1}}\n", "ui: {progress: {pct: x}}\n"):
        with pytest.raises(SettingsError, match="ui.progress"):
            parse_settings(bad)


def test_the_settings_mapping_drives_an_outer_runs_declared_progress(store):
    client, storage, outer = store
    write_settings(storage, APP, MAPPING)
    body = _summary(client, outer)
    assert body["declared_progress"]["done"] == 20
    assert body["declared_progress"]["total"] == 60
    assert body["declared_progress"]["unit"] == "dates"
    assert body["progress"] == round(20 / 60, 4)
    assert body["total"] == 3
    job = _jobs_row(client)
    assert job["declared_progress"]["unit"] == "dates" and job["progress"] == round(20 / 60, 4)


def test_a_settings_change_reaches_the_rollups_without_a_new_generation(store):
    client, _, outer = store
    assert _summary(client, outer)["declared_progress"] is None
    assert _jobs_row(client)["declared_progress"] is None
    r = client.put(f"{BASE}/settings", json={"text": MAPPING})
    assert r.status_code == 200, r.text
    assert _summary(client, outer)["declared_progress"]["total"] == 60
    assert _jobs_row(client)["declared_progress"]["total"] == 60
    client.put(f"{BASE}/settings", json={"text": ""})
    assert _summary(client, outer)["declared_progress"] is None


def test_a_settings_change_changes_the_etags(store):
    client, _, outer = store
    urls = [f"{BASE}/experiments/{outer}/summary", f"{BASE}/experiments?top=jobs&limit=50"]
    etags = [client.get(url).headers["etag"] for url in urls]
    client.put(f"{BASE}/settings", json={"text": MAPPING})
    for url, etag in zip(urls, etags):
        assert client.get(url, headers={"If-None-Match": etag}).status_code == 200, url


def test_a_git_workspaces_conf_names_them_too(tmp_path):
    from vmn_exp.storage.local import LocalSnapshotStorage
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = LocalSnapshotStorage(str(root / ".vmn" / "store"), "runs")
    outer = _run(storage, 1, {"dates_done": 5, "dates_total": 10})
    _run(storage, 2, {"loss": 1.0}, parent=outer)
    folder = root / ".vmn" / APP
    folder.mkdir()
    (folder / "conf.yml").write_text(yaml.dump(
        {"conf": {"experiment": {"ui": yaml.safe_load(MAPPING)["ui"]}}}))
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    body = _summary(TestClient(create_app(manager)), outer)
    assert body["declared_progress"]["unit"] == "dates" and body["progress"] == 0.5
