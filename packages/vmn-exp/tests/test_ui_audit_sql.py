"""Audit pages, counts and exports in SQL; retention and the expiry sweep
(plan 25 F5)."""
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.ui.audit import AuditLog
from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.principal import ADMIN, Principal
from vmn_exp.ui.auth.sessions import SessionService
from vmn_exp.ui.config import ConfigError, parse_config
from vmn_exp.ui.control_plane import SQLiteControlPlane
from vmn_exp.ui.control_plane_sweep import ControlPlaneSweeper

DAY = 86400.0
ADMIN_HDR = {"Authorization": "Bearer a"}


class _Admin:
    def authenticate(self, request):
        if request.headers.get("Authorization") == "Bearer a":
            return Principal("u:admin", "Ada", {"*": ADMIN})
        return None


@pytest.fixture
def cp(tmp_path):
    return SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))


def _no_full_list(monkeypatch, cp):
    def refuse(kind):
        raise AssertionError(f"listed every {kind}")

    monkeypatch.setattr(cp, "list", refuse)


def _client(tmp_path, cp):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    return TestClient(create_app(WorkspaceManager(str(tmp_path / "ui")),
                                 auth=AuthenticatorChain([_Admin()]), control_plane=cp))


def test_page_and_count_never_list_every_entry(cp, monkeypatch):
    log = AuditLog(cp)
    for i in range(5):
        log.record(actor="u", action=str(i))
    _no_full_list(monkeypatch, cp)
    assert [e["action"] for e in log.page(offset=1, limit=2)] == ["3", "2"]
    assert log.count() == 5


def test_a_page_query_carries_its_limit(cp):
    log = AuditLog(cp)
    for i in range(50):
        log.record(actor="u", action=str(i))
    seen = []
    cp._db.set_trace_callback(seen.append)
    log.page(offset=0, limit=3)
    cp._db.set_trace_callback(None)
    (sql,) = [s for s in seen if "vmn_audit" in s]
    assert "LIMIT 3" in sql
    plan = cp._db.execute("EXPLAIN QUERY PLAN " + sql).fetchall()
    assert not [row for row in plan if "TEMP B-TREE" in row[-1]]


def test_audit_api_pages_and_counts_in_sql(tmp_path, cp, monkeypatch):
    log = AuditLog(cp)
    for i in range(3):
        log.record(actor="u", action=str(i))
    client = _client(tmp_path, cp)
    _no_full_list(monkeypatch, cp)
    body = client.get("/api/v1/audit", params={"limit": 2}, headers=ADMIN_HDR).json()
    assert body["total"] == 3 and [e["action"] for e in body["entries"]] == ["2", "1"]


def test_export_streams_every_entry_oldest_first(tmp_path, cp, monkeypatch):
    log = AuditLog(cp)
    for i in range(1200):
        log.record(actor="u", action=str(i))
    client = _client(tmp_path, cp)
    _no_full_list(monkeypatch, cp)
    r = client.get("/api/v1/audit/export", headers=ADMIN_HDR)
    assert r.status_code == 200 and "ndjson" in r.headers["content-type"]
    assert "content-length" not in r.headers  # streamed, not built in memory
    assert [json.loads(line)["action"] for line in r.text.splitlines()] == [
        str(i) for i in range(1200)]


def test_sweep_applies_audit_retention_and_expiry(cp):
    now = 1_000 * DAY
    stamps = iter([now - 40 * DAY, now - 10 * DAY])
    log = AuditLog(cp, clock=lambda: next(stamps))
    log.record(actor="u", action="old")
    log.record(actor="u", action="recent")
    cp.put("session", "gone", {}, expires_at=now - 1)
    cp.put("session", "kept", {}, expires_at=now + 1)
    ControlPlaneSweeper(cp, retention_days=30, clock=lambda: now).sweep()
    assert [e["action"] for e in cp.scan("audit")] == ["recent"]
    assert cp.get("session", "gone") is None and cp.get("session", "kept") == {}


def test_the_sweeper_runs_at_start_and_stops(cp):
    cp.put("login", "gone", {}, expires_at=1)
    sweeper = ControlPlaneSweeper(cp, interval_sec=3600)
    sweeper.start()
    sweeper.stop()
    assert cp.get("login", "gone") is None


def test_the_server_sweeps_hourly_from_startup(tmp_path, cp):
    from vmn_exp.ui.control_plane_sweep import SWEEP_INTERVAL_SEC

    cp.put("session", "gone", {}, expires_at=1)
    with _client(tmp_path, cp) as client:
        sweeper = client.app.state.sweeper
        assert sweeper.interval_sec == SWEEP_INTERVAL_SEC == 3600
        sweeper.wait_first()
    assert cp.get("session", "gone") is None


def test_a_login_sweeps_expired_sessions(cp):
    cp.put("session", "stale", {}, expires_at=5)
    SessionService(cp, clock=lambda: 10.0).open(Principal("u:a", "A", {}))
    assert cp.get("session", "stale") is None


def test_server_yml_retention_reaches_the_sweeper(tmp_path):
    import argparse

    from vmn_exp.ui.cli import build_server, server_app

    path = tmp_path / "server.yml"
    path.write_text(f"data_dir: {tmp_path / 'data'}\naudit: {{retention_days: 7}}\n")
    args = argparse.Namespace(
        host="127.0.0.1", port=8265, token=None, data_dir=None, db=None, config=str(path),
        repo=None, store=None, read_only=False, no_index=False, allowed_host=None)
    manager, cfg, cp = build_server(args, env={})
    app = server_app(manager, cfg, cp, args, env={}, token="t")
    assert app.state.sweeper.retention_days == 7


def test_retention_days_parse_with_a_one_year_default():
    assert parse_config({}).audit.retention_days == 365
    assert parse_config({"audit": {"retention_days": 30}}).audit.retention_days == 30
    for bad in (0, -1, "x", True):
        with pytest.raises(ConfigError):
            parse_config({"audit": {"retention_days": bad}})
    with pytest.raises(ConfigError):
        parse_config({"audit": {"keep": 1}})
