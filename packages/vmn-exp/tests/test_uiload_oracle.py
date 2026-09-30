"""Unit tests for the uiload status oracle (pure Python, no Docker)."""
import json

from uiload import oracle

STALE = 5.0


def ev(t, event, job="j", pid=100, **extra):
    return {"t": t, "job_id": job, "event": event, "pid": pid, **extra}


def status(events, now, grace=1.0):
    return oracle.expected_status(events, now, STALE, grace_sec=grace)


def test_not_started_is_ambiguous():
    assert status([], 10) is None
    assert status([ev(0, "spawned")], 10) is None


def test_running_after_start_grace():
    events = [ev(0, "started", verstr="v")]
    assert status(events, 0.5) is None
    assert status(events, 2) == "running"


def test_future_events_are_ignored():
    events = [ev(0, "started"), ev(50, "finished", exit_code=0)]
    assert status(events, 10) == "running"


def test_finished_success_and_failure():
    ok = [ev(0, "started"), ev(10, "finished", exit_code=0)]
    assert status(ok, 10.5) is None
    assert status(ok, 12) == "succeeded"
    bad = [ev(0, "started"), ev(10, "finished", exit_code=1)]
    assert status(bad, 12) == "failed"


def test_oom_goes_stuck_after_stale_window():
    events = [ev(0, "started"), ev(10, "oom")]
    assert status(events, 11) == "running"
    assert status(events, 14) is None
    assert status(events, 10 + STALE + 0.5) is None
    assert status(events, 10 + STALE + 2) == "stuck"


def test_stuck_then_recovers_then_succeeds():
    events = [
        ev(0, "started"), ev(10, "stopping", resume_after_sec=12),
        ev(22, "resumed"), ev(40, "finished", exit_code=0),
    ]
    assert status(events, 20) == "stuck"
    assert status(events, 22.5) is None
    assert status(events, 30) == "running"
    assert status(events, 45) == "succeeded"


def test_signalled_is_ambiguous_until_finished():
    events = [ev(0, "started"), ev(10, "signalled", signal=15)]
    assert status(events, 60) is None
    events.append(ev(11, "finished", exit_code=143))
    assert status(events, 60) == "failed"


def test_teardown_is_ambiguous():
    events = [ev(0, "started"), ev(10, "teardown")]
    assert status(events, 20) is None
    done = [ev(0, "started"), ev(5, "finished", exit_code=0), ev(10, "teardown")]
    assert status(done, 20) == "succeeded"


def _write(path, lines, tail=""):
    path.write_text("".join(json.dumps(x) + "\n" for x in lines) + tail)


def _events_dir(tmp_path):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    return events_dir


def _names(events):
    return [e["event"] for e in events]


def test_load_events_merges_files_sorted_and_tolerates_truncation(tmp_path):
    events_dir = _events_dir(tmp_path)
    _write(events_dir / "worker-100.jsonl",
           [ev(2, "finished", exit_code=0), ev(1, "started")], tail='{"t": 3, "jo')
    _write(events_dir / "driver.jsonl", [ev(0.5, "spawned")])
    loaded = oracle.load_events(tmp_path)
    assert _names(loaded["j"]) == ["spawned", "started", "finished"]


def test_load_events_missing_dir_is_empty(tmp_path):
    assert oracle.load_events(tmp_path) == {}


def test_process_events_apply_to_every_job_of_that_pid(tmp_path):
    events_dir = _events_dir(tmp_path)
    _write(events_dir / "worker-100.jsonl", [
        ev(0, "started", job="outer"),
        ev(1, "started", job="inner-a"),
        ev(2, "started", job="inner-done"),
        ev(3, "finished", job="inner-done", exit_code=0),
        ev(10, "oom", job="outer"),
    ])
    _write(events_dir / "worker-200.jsonl", [ev(0, "started", job="other", pid=200)])
    loaded = oracle.load_events(tmp_path)
    assert _names(loaded["outer"]) == ["started", "oom"]
    assert _names(loaded["inner-a"]) == ["started", "oom"]
    assert _names(loaded["inner-done"]) == ["started", "finished"]
    assert _names(loaded["other"]) == ["started"]
    assert oracle.expected_status(loaded["inner-a"], 30, STALE) == "stuck"


def test_process_events_skip_jobs_of_a_reused_pid(tmp_path):
    events_dir = _events_dir(tmp_path)
    _write(events_dir / "worker-100.jsonl", [
        ev(0, "started", job="old"),
        ev(1, "oom", job="old"),
        ev(20, "started", job="new"),
        ev(30, "stopping", job="new"),
    ])
    loaded = oracle.load_events(tmp_path)
    assert _names(loaded["old"]) == ["started", "oom"]
    assert _names(loaded["new"]) == ["started", "stopping"]


def test_expected_counts():
    by_job = {
        "a": [ev(0, "started", job="a")],
        "b": [ev(0, "started", job="b"), ev(1, "finished", job="b", exit_code=0)],
        "c": [ev(0, "spawned", job="c")],
    }
    counts, ambiguous = oracle.expected_counts(by_job, 10, STALE)
    assert counts == {"running": 1, "succeeded": 1}
    assert ambiguous == 1
