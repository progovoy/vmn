"""Plan 23 S1: what one job's rollup says — expected size, progress,
throughput, ETA, best, failures — from its subtree's tallies."""
import datetime

from leaderboard_fleet import T0, iso
from vmn_exp.ui.job_rollup_payload import job_payload, job_summary
from vmn_exp.ui.job_tally import RollupSpec, Tally

SCHEMA = {"loss": {"goal": "min", "primary": True}, "acc": {"goal": "max"}}
SPEC = RollupSpec(SCHEMA)


def _row(n, status="succeeded", ago=None, **fields):
    row = {"verstr": f"v{n:03d}", "parent": "job", "status": status, "metrics": {},
           "exit_code": {"succeeded": 0, "failed": 1}.get(status)}
    if ago is not None:
        end = T0 - datetime.timedelta(seconds=ago)
        row.update(started_at=iso(end - datetime.timedelta(seconds=100)),
                   finished_at=iso(end), duration_sec=100.0)
    return dict(row, **fields)


def _payload(rows, job=None, parts=None):
    job = job or {"verstr": "job", "params": {}}
    return job_payload(job, parts or [Tally.of(rows, SPEC)], SPEC, T0)


def test_expected_is_the_sweep_size_else_expected_pods_else_the_runs_so_far():
    rows = [_row(i) for i in range(4)]
    assert _payload(rows)["expected"] == 4
    assert _payload(rows, {"verstr": "job", "params": {"expected_pods": 10}})["expected"] == 10
    job = {"verstr": "job", "sweep_planned": 20, "params": {"expected_pods": 10}}
    assert _payload(rows, job)["expected"] == 20
    assert _payload(rows, job)["progress"] == 0.2


def test_counts_use_the_job_states_and_failed_pct_is_over_all_runs():
    rows = [_row(0), _row(1, "failed"), _row(2, "running"), _row(3, "created"),
            _row(4, "stuck")]
    payload = _payload(rows)
    assert payload["counts"] == {"running": 1, "waiting": 1, "succeeded": 1,
                                 "failed": 1, "stuck": 1}
    assert payload["done"] == 2 and payload["total"] == 5
    assert payload["failed_pct"] == 20.0


def test_throughput_counts_the_last_ten_minutes_and_gives_an_eta():
    rows = [_row(i, ago=30 * i) for i in range(30)]  # one every 30 s over 15 min
    job = {"verstr": "job", "sweep_planned": 50}
    payload = _payload(rows, job)
    # The current minute (T0 starts one) and the nine before it.
    recent = sum(1 for i in range(30) if 30 * i <= 540)
    assert payload["throughput_per_min"] == recent / 10
    assert payload["eta_sec"] == round(20 / (recent / 10) * 60)


def test_no_recent_completion_means_no_eta_and_a_finished_job_has_none_left():
    stale = [_row(0, ago=3600), _row(1, "running")]
    assert _payload(stale)["throughput_per_min"] == 0
    assert _payload(stale)["eta_sec"] is None
    assert _payload([_row(0, ago=3600)])["eta_sec"] == 0


def test_best_follows_the_goal_and_ties_go_to_the_lowest_verstr():
    rows = [_row(i, metrics={"loss": loss, "acc": acc})
            for i, (loss, acc) in enumerate([(0.5, 0.1), (0.2, 0.9), (0.2, 0.9), (0.9, 0.3)])]
    metrics = _payload(rows)["metrics"]
    assert (metrics["loss"]["best"], metrics["loss"]["best_verstr"]) == (0.2, "v001")
    assert (metrics["acc"]["best"], metrics["acc"]["best_verstr"]) == (0.9, "v001")
    assert metrics["loss"]["min"] == 0.2 and metrics["loss"]["max"] == 0.9
    assert metrics["loss"]["n"] == 4 and abs(metrics["loss"]["mean"] - 0.45) < 1e-12


def test_a_metric_no_run_carries_reads_as_none():
    assert _payload([_row(0)])["metrics"] == {"loss": None, "acc": None}


def test_failures_are_the_top_ten_signatures_with_labels():
    rows = [_row(i, "failed", error_summary=f"err{chr(97 + i % 12)} at {i}") for i in range(40)]
    failures = _payload(rows)["failures"]
    assert len(failures) == 10
    assert [f["count"] for f in failures] == sorted((f["count"] for f in failures), reverse=True)
    assert all(f["label"].startswith("err") for f in failures)


def test_the_full_rollup_names_its_main_metric_so_the_page_needs_no_guess():
    assert _payload([_row(1, metrics={"loss": 0.5})])["metric"] == "loss"
    assert job_payload({"verstr": "job", "params": {}}, [Tally.of([], RollupSpec({}))],
                       RollupSpec({}), T0)["metric"] is None


def test_parts_add_up_like_one_tally():
    rows = [_row(i, ago=10 * i, metrics={"loss": i / 10}) for i in range(20)]
    whole = _payload(rows)
    split = _payload(None, parts=[Tally.of(rows[:7], SPEC), Tally.of(rows[7:], SPEC)])
    assert split == whole


def test_the_summary_is_compact_and_carries_the_main_metrics_best_and_spread():
    rows = [_row(i, ago=10 * i, metrics={"loss": i / 10}) for i in range(20)]
    summary = job_summary({"verstr": "job"}, [Tally.of(rows, SPEC)], SPEC, T0)
    assert summary["metric"] == "loss"
    assert (summary["best"], summary["best_verstr"]) == (0.0, "v000")
    assert sum(summary["spread"]) == 20
    assert "metrics" not in summary and "failures" not in summary
    assert summary["counts"]["succeeded"] == 20
