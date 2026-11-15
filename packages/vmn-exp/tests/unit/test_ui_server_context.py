"""The resolvers the UI routes share (plan 44 G6), tested without building
the FastAPI app."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from vmn_exp.ui.memo import TTLCache
from vmn_exp.ui.server_context import ServerContext
from fakes.clock import FakeClock
from fakes.env import FakeEnv


class FakeManager:
    def __init__(self, *workspaces):
        self._workspaces = {ws.name: ws for ws in workspaces}

    def get(self, name):
        return self._workspaces.get(name)


def _store_ws(name="st"):
    return SimpleNamespace(name=name, kind="store", store=f"s3://bucket/{name}",
                           path=None, capabilities=None)


def _refuse(*args, **kwargs):
    raise AssertionError("not expected in this test")


def _ctx(manager, open_workspace_storage=_refuse):
    return ServerContext(manager, source=None, app_lists=TTLCache(5),
                         open_workspace_storage=open_workspace_storage,
                         open_edit_storage=_refuse, probe_store=_refuse, app_exists=_refuse, clock=FakeClock(),
                         env=FakeEnv())


def test_unknown_workspace_is_404():
    ctx = _ctx(FakeManager(_store_ws()))

    with pytest.raises(HTTPException) as raised:
        ctx.workspace("nope")

    assert raised.value.status_code == 404
    assert "nope" in raised.value.detail


def test_store_workspace_storage_is_built_once_and_reused():
    opened = []

    def opener(ws):
        opened.append(ws.name)
        return object()

    ws = _store_ws()
    ctx = _ctx(FakeManager(ws), open_workspace_storage=opener)

    first, second = ctx.exp_storage_for(ws), ctx.exp_storage_for(ws)

    assert first is second
    assert opened == ["st"]


def test_unusable_store_is_404_with_its_message():
    def opener(ws):
        raise ValueError(f"no vmn store at {ws.store}")

    ws = _store_ws()
    ctx = _ctx(FakeManager(ws), open_workspace_storage=opener)

    with pytest.raises(HTTPException) as raised:
        ctx.exp_storage_for(ws)

    assert (raised.value.status_code, raised.value.detail) == (404, "no vmn store at s3://bucket/st")


@pytest.mark.parametrize("app_tag", ["..", "-etc", "a-..-b", "a\\b"])
def test_invalid_app_tag_is_rejected(app_tag):
    with pytest.raises(HTTPException) as raised:
        _ctx(FakeManager()).app_name(app_tag)

    assert raised.value.status_code == 400
