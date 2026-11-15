"""The UI server's request gate, org binding and audit recorder are plain
ASGI middleware (a BaseHTTPMiddleware leaves cyclic garbage per request):
driven here with scope dicts and a tiny inner app, no server and no client."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from vmn_exp.ui.audit import AuditRecorder
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import EDITOR, Principal
from vmn_exp.ui.middleware import RequestGate
from vmn_exp.ui.tenancy import OrgBinding, current_org


def _scope(method="GET", path="/api/x", state=None):
    scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(),
             "root_path": "", "query_string": b"", "headers": [], "scheme": "http",
             "server": ("testserver", 80)}
    if state is not None:
        scope["state"] = state
    return scope


class _Inner:
    """Answers *status* in two body chunks, noting what it saw on the way."""

    def __init__(self, events, status=200, route=None):
        self.events, self.status, self.route = events, status, route

    async def __call__(self, scope, receive, send):
        self.events.append(("app", scope["type"], dict(scope.get("state", {})), current_org()))
        if self.route is not None:  # as the router does, on the shared scope
            scope.update(route=self.route, path_params={"ws_name": "ws"})
        await send({"type": "http.response.start", "status": self.status, "headers": []})
        await send({"type": "http.response.body", "body": b"a", "more_body": True})
        await send({"type": "http.response.body", "body": b"b"})


def _serve(middleware, scope, events):
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        events.append(("send", message["type"], message.get("status", message.get("body"))))

    asyncio.run(middleware(scope, receive, send))
    return events


def _sent(events):
    return [e[1:] for e in events if e[0] == "send"]


# -- RequestGate --------------------------------------------------------------

def test_gate_passes_the_request_on_when_check_answers_none():
    events = []

    async def check(request):
        request.state.principal = "p"
        return None

    _serve(RequestGate(_Inner(events), check=check), _scope(), events)
    assert events[0] == ("app", "http", {"principal": "p"}, None)
    assert _sent(events) == [("http.response.start", 200), ("http.response.body", b"a"),
                             ("http.response.body", b"b")]


def test_gate_sends_the_refusal_and_never_calls_the_app():
    events = []

    async def check(request):
        return JSONResponse({"detail": "no"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

    _serve(RequestGate(_Inner(events), check=check), _scope(), events)
    assert [e[0] for e in events] == ["send", "send"]
    assert _sent(events) == [("http.response.start", 401), ("http.response.body", b'{"detail":"no"}')]


def test_gate_leaves_non_http_scopes_unchecked():
    events = []

    async def check(request):
        raise AssertionError("checked")

    _serve(RequestGate(_Inner(events), check=check), {"type": "lifespan"}, events)
    assert events[0][:2] == ("app", "lifespan")


# -- OrgBinding ---------------------------------------------------------------

def test_multi_tenancy_binds_the_principal_org_for_the_request_only():
    events = []
    principal = Principal("u", "u", org_id=7)
    _serve(OrgBinding(_Inner(events), tenancy="multi"), _scope(state={"principal": principal}), events)
    assert events[0] == ("app", "http", {"principal": principal, "org_id": 7}, 7)
    assert current_org() is None
    assert [s for _, s in _sent(events)][0] == 200


def test_multi_tenancy_refuses_a_principal_without_an_org():
    events = []
    _serve(OrgBinding(_Inner(events), tenancy="multi"), _scope(state={"principal": Principal("u", "u")}),
           events)
    assert _sent(events) == [("http.response.start", 403),
                             ("http.response.body", b'{"detail":"No organization for this principal"}')]


def test_multi_tenancy_lets_an_anonymous_request_through_in_org_zero():
    events = []
    _serve(OrgBinding(_Inner(events), tenancy="multi"), _scope(), events)
    assert events[0] == ("app", "http", {"org_id": 0}, 0)


def test_single_tenancy_sets_org_zero_and_binds_no_context():
    events = []
    principal = Principal("u", "u", org_id=7)
    _serve(OrgBinding(_Inner(events), tenancy="single"), _scope(state={"principal": principal}), events)
    assert events[0] == ("app", "http", {"principal": principal, "org_id": 0}, None)


# -- AuditRecorder ------------------------------------------------------------

def _endpoint():
    return None


EDIT_ROUTE = APIRoute("/w/{ws_name}/x", _endpoint, methods=["POST"], dependencies=[require(EDITOR)])


class _FakeAudit:
    def __init__(self, events, fail=None):
        self.events, self.fail = events, fail

    def record_principal(self, principal, action, **fields):
        if self.fail:
            raise self.fail
        self.events.append(("audit", principal, action, fields))


def test_audit_records_a_mutation_with_its_status_before_the_response_starts():
    events = []
    state = SimpleNamespace(audit=_FakeAudit(events))
    recorder = AuditRecorder(_Inner(events, status=409, route=EDIT_ROUTE), state=state)
    _serve(recorder, _scope("POST", "/w/ws/x", state={"principal": "p"}), events)
    assert events[1] == ("audit", "p", "POST /w/{ws_name}/x",
                         {"path": "/w/ws/x", "workspace": "ws", "status": 409})
    assert _sent(events) == [("http.response.start", 409), ("http.response.body", b"a"),
                             ("http.response.body", b"b")]


def test_audit_skips_reads_and_a_server_without_an_audit_log():
    events = []
    state = SimpleNamespace(audit=_FakeAudit(events))
    _serve(AuditRecorder(_Inner(events, route=EDIT_ROUTE), state=state), _scope("GET"), events)
    _serve(AuditRecorder(_Inner(events, route=EDIT_ROUTE), state=SimpleNamespace()),
           _scope("POST"), events)
    assert not [e for e in events if e[0] == "audit"]


def test_audit_records_an_anonymous_request_as_no_principal():
    events = []
    state = SimpleNamespace(audit=_FakeAudit(events))
    _serve(AuditRecorder(_Inner(events, route=EDIT_ROUTE), state=state), _scope("POST", "/w/ws/x"), events)
    assert events[1][:2] == ("audit", None)


def test_a_failed_audit_record_propagates_and_sends_nothing():
    events = []
    state = SimpleNamespace(audit=_FakeAudit(events, fail=OSError("down")))
    with pytest.raises(OSError, match="down"):
        _serve(AuditRecorder(_Inner(events, route=EDIT_ROUTE), state=state), _scope("POST"), events)
    assert _sent(events) == []
