"""The job action routes (plan 44 G6) on a bare FastAPI app, with a
ServerContext over fakes and a recording job runner."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from vmn_exp.ui import routes_actions
from vmn_exp.ui.memo import TTLCache
from vmn_exp.ui.server_context import ServerContext
from fakes.clock import FakeClock
from fakes.env import FakeEnv

PREFIX = "/api/v1"
RUN = "0.0.1-dev.a"


class FakeManager:
    def __init__(self, *workspaces):
        self._workspaces = {ws.name: ws for ws in workspaces}

    def get(self, name):
        return self._workspaces.get(name)


class FakeSnapshot:
    def declared_schema(self):
        return {}


class FakeSource:
    def workspace_index(self, ws):
        return SimpleNamespace(storage=object())

    def app_settings(self, ws, app_name, storage):
        return {}

    def metrics_schema(self, ws, app_name, settings):
        return {}

    def snapshot(self, ws, app_name, storage, schema=None):
        return FakeSnapshot()


class FakeLeaderboards:
    def __init__(self, rows):
        self.rows = rows

    def now(self):
        return FakeClock().now()

    def ordered(self, snapshot, schema, **filters):
        return self.rows


class RecordingJobs:
    def __init__(self):
        self.submitted = []

    def _record(self, *args):
        self.submitted.append(args)
        return {"id": "j", "status": "running"}, None

    def submit(self, *args):
        return self._record(*args)

    def submit_call(self, *args):
        return self._record(*args)

    def submit_bulk(self, *args):
        return self._record(*args)


def _refuse(*args, **kwargs):
    raise AssertionError("not expected in this test")


def _client(ws, jobs, read_only=False, rows=()):
    ctx = ServerContext(FakeManager(ws), FakeSource(), TTLCache(5), open_workspace_storage=_refuse,
                        open_edit_storage=_refuse, probe_store=_refuse, app_exists=_refuse, clock=FakeClock(),
                        env=FakeEnv())
    app = FastAPI()
    routes_actions.register(app, PREFIX, ctx, jobs, FakeLeaderboards(list(rows)), read_only)
    return TestClient(app)


def _git_ws():
    return SimpleNamespace(name="g", kind="git", path="/checkout", store=None, capabilities=None)


def _store_ws(capabilities):
    return SimpleNamespace(name="st", kind="store", path=None, store="s3://b/st",
                           capabilities=capabilities)


def test_read_only_server_refuses_actions():
    jobs = RecordingJobs()
    client = _client(_git_ws(), jobs, read_only=True)

    resp = client.post(f"{PREFIX}/workspaces/g/apps/app/actions/exp_archive", json={"verstr": RUN})

    assert resp.status_code == 403
    assert jobs.submitted == []


def test_store_action_without_edit_capability_is_403():
    jobs = RecordingJobs()
    client = _client(_store_ws(["read"]), jobs)

    resp = client.post(f"{PREFIX}/workspaces/st/apps/app/actions/note",
                       json={"verstr": RUN, "note": "hi"})

    assert resp.status_code == 403
    assert "edit access" in resp.json()["detail"]
    assert jobs.submitted == []


def test_bulk_dry_run_returns_a_preview_without_a_job():
    jobs = RecordingJobs()
    rows = [{"verstr": "0.0.1-dev.a"}, {"verstr": "0.0.1-dev.b", "archived": True}]
    client = _client(_git_ws(), jobs, rows=rows)

    resp = client.post(f"{PREFIX}/workspaces/g/apps/app/actions/exp_archive",
                       json={"q": "status = failed", "dry_run": True})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"count": 1, "sample": ["0.0.1-dev.a"]}
    assert jobs.submitted == []
