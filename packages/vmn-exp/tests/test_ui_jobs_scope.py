"""A job remembers the workspace and org it ran in (plan 42 E6), off its payload."""
import pytest

from vmn_exp.ui.jobs import JobRunner
from vmn_exp.ui.tenancy import org_context


def test_job_records_workspace_and_org():
    runner = JobRunner()
    with org_context(7):  # what the org middleware binds for a request
        job, err = runner.submit_call("ws", ["exp", "tag"], lambda: "ok")
    assert err is None
    scoped, workspace, org_id = runner.get_scoped(job["id"])
    assert (scoped["id"], workspace, org_id) == (job["id"], "ws", 7)
    assert "workspace" not in scoped and "org_id" not in scoped


def test_job_outside_a_request_org_is_single_tenant():
    runner = JobRunner()
    job, _ = runner.submit_call("ws", ["exp", "tag"], lambda: "ok")
    assert runner.get_scoped(job["id"])[2] == 0


def test_job_submitted_by_a_request_records_its_org():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from vmn_exp.ui.auth.principal import Principal
    from vmn_exp.ui.tenancy import install_org_middleware

    runner, app = JobRunner(), FastAPI()
    install_org_middleware(app, "multi")

    @app.middleware("http")
    async def authn(request: Request, call_next):
        request.state.principal = Principal("u", "u", org_id=3)
        return await call_next(request)

    @app.post("/submit")
    def submit():  # a sync route, on a pool thread like the server's
        return runner.submit_call("ws", ["exp", "tag"], lambda: "ok")[0]

    job = TestClient(app).post("/submit").json()
    assert runner.get_scoped(job["id"])[1:] == ("ws", 3)


def test_unknown_job_is_not_scoped():
    assert JobRunner().get_scoped("nope") is None
