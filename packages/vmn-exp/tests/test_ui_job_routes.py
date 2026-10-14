"""Plan 23 S3 over HTTP: ``.../experiments/{v}/summary`` and
``.../failures`` of a job (404 for any other run, ETag/304), the run
detail of a job without ``fleet.children``, and ``.../sweep`` capped at 50
trials with the job's counts from the rollup."""
import pytest
from run_code_seed import client, finished_state, metrics, run_url, seed_run
from vmn_exp.core.sweep.spec import parse_spec

pytest.importorskip("fastapi")

OUTER = "0.0.1-dev.r0001"
LOSS_GOAL = {"type": "define_metric", "name": "loss", "goal": "min"}


def _kid(n):
    return f"0.0.1-dev.r{n + 2:04d}"


def _failed(summary):
    return dict(finished_state(1), error_summary=summary, host="gpu1")


def _seed_job(app_layout, kids=6, **outer):
    seed_run(app_layout, OUTER, 1, finished_state(0), name="grid", entries=[LOSS_GOAL],
             **outer)
    for n in range(kids):
        state = _failed(f"CUDA out of memory at {n}") if n < 2 else finished_state(0)
        seed_run(app_layout, _kid(n), n % 50 + 2, state, parent=OUTER, name=f"k{n}",
                 entries=[{"type": "params", "params": {"bs": 512 if n < 2 else 64}},
                          metrics({"loss": n / 10})])


def test_the_summary_of_a_job_carries_the_rollup_top_and_timeline(app_layout):
    _seed_job(app_layout)
    resp = client(app_layout).get(run_url(app_layout, OUTER, "/summary"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["name"], body["kind"], body["sweep"]) == ("grid", "outer", False)
    assert body["total"] == 6 and body["counts"]["failed"] == 2
    assert isinstance(body["idx"], int) and body["tree_status"] == "failed"
    assert body["timeline"]["bucket_sec"] == 60
    assert [t["name"] for t in body["top"]] == ["k0", "k1", "k2", "k3", "k4", "k5"]
    assert body["top"][0] == {"verstr": _kid(0), "idx": body["top"][0]["idx"], "name": "k0",
                              "status": "failed", "value": 0.0}


def test_a_repeated_summary_poll_answers_304(app_layout):
    _seed_job(app_layout)
    http = client(app_layout)
    first = http.get(run_url(app_layout, OUTER, "/summary"))
    again = http.get(run_url(app_layout, OUTER, "/summary"),
                     headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


@pytest.mark.parametrize("tail", ["/summary", "/failures"])
def test_a_run_without_children_is_404(app_layout, tail):
    _seed_job(app_layout)
    http = client(app_layout)
    assert http.get(run_url(app_layout, _kid(0), tail)).status_code == 404
    assert http.get(run_url(app_layout, "0.0.9-dev.nope", tail)).status_code == 404


def test_failures_cluster_the_jobs_failed_runs(app_layout):
    _seed_job(app_layout, kids=8)
    http = client(app_layout)
    resp = http.get(run_url(app_layout, OUTER, "/failures"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_failed"] == 2
    (cluster,) = body["clusters"]
    assert cluster["count"] == 2 and cluster["share"] == 1.0
    assert cluster["hosts"] == [{"host": "gpu1", "count": 2}]
    assert cluster["params"] == []  # 2 runs: below the 5-run support (test_ui_job_failures.py)
    assert cluster["example_verstr"] in (_kid(0), _kid(1))
    again = http.get(run_url(app_layout, OUTER, "/failures"),
                     headers={"If-None-Match": resp.headers["etag"]})
    assert again.status_code == 304


def test_the_detail_of_a_job_has_rollup_counts_and_no_children_table(app_layout):
    _seed_job(app_layout, params={"expected_pods": 10})
    resp = client(app_layout).get(run_url(app_layout, OUTER))
    assert resp.status_code == 200, resp.text
    status = resp.json()["status"]
    assert "children" not in status["fleet"]
    assert status["fleet"]["counts"]["failed"] == 2
    assert status["fleet"]["counts"]["succeeded"] == 4
    assert status["tree_status"] == "failed" and status["kind"] == "outer"
    assert len(status["children"]) == 6


SPEC = {"method": "grid", "metric": {"name": "loss", "goal": "min"},
        "parameters": {"x": {"values": list(range(60))}}}


def test_the_sweep_caps_its_trials_and_counts_from_the_rollup(app_layout):
    parse_spec(SPEC)
    seed_run(app_layout, OUTER, 1, sweep=SPEC, name="sw")
    for n in range(55):
        tags = {"sweep": OUTER, "sweep_trial": str(n), "sweep_attempt": "0"}
        seed_run(app_layout, _kid(n), n % 50 + 2, finished_state(0), parent=OUTER,
                 entries=[{"type": "create", "tags": tags}, metrics({"loss": n})])
    resp = client(app_layout).get(run_url(app_layout, OUTER, "/sweep"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trials_total"] == 55
    assert [t["trial"] for t in body["trials"]] == list(range(50))
    assert body["job"]["counts"]["succeeded"] == 55
    assert body["job"]["expected"] == 60
    assert body["summary"]["best"]["value"] == 0


def test_the_detail_of_a_job_reads_no_child_run_state(app_layout, monkeypatch):
    from vmn_exp.ui.readers import experiments as exp_reader

    _seed_job(app_layout)
    http = client(app_layout)
    http.get(f"/api/v1/workspaces/main/apps/{app_layout.app_name}/experiments")
    read, real = [], exp_reader.load_run_state
    monkeypatch.setattr(exp_reader, "load_run_state",
                        lambda storage, app, verstr: read.append(verstr) or real(storage, app, verstr))
    assert http.get(run_url(app_layout, OUTER)).status_code == 200
    assert read and set(read) <= {OUTER}


GOALS = [{"type": "define_metric", "name": n, "goal": g}
         for n, g in (("acc", "max"), ("f1", "max"), ("loss", "min"))]


def test_job_endpoints_rank_on_the_goals_runs_declare_without_a_conf(app_layout):
    seed_run(app_layout, OUTER, 1, finished_state(0), name="grid")
    for n in range(6):
        seed_run(app_layout, _kid(n), n + 2, finished_state(0), parent=OUTER,
                 entries=GOALS + [metrics({"acc": n / 10, "f1": n / 5, "loss": 1 - n / 10})])
    http = client(app_layout)
    api = f"/api/v1/workspaces/main/apps/{app_layout.app_name}"
    schema = http.get(f"{api}/metrics-schema").json()
    assert schema == {"acc": {"goal": "max"}, "f1": {"goal": "max"}, "loss": {"goal": "min"}}
    body = http.get(run_url(app_layout, OUTER, "/summary")).json()
    assert body["ranked"] is True and body["metric"] == "acc"
    assert set(body["metrics"]) == {"acc", "f1", "loss"}
    assert body["metrics"]["loss"]["best_verstr"] == _kid(5)
    assert body["top"][0]["verstr"] == _kid(5)
    (job,) = [r["job"] for r in http.get(f"{api}/experiments?top=1").json()]
    assert (job["metric"], job["best_verstr"]) == ("acc", _kid(5))
