"""The ui job runner: no inherited stdin, bounded runtime, bounded memory."""
import sys
import time

from version_stamp.ui.jobs import MAX_JOB_LOG_BYTES, JobRunner


def _wait(runner, job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = runner.get(job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def _py(code):
    # argv[0] is not on PATH, so the runner falls back to sys.executable -m ...;
    # give it a real executable path instead.
    return [sys.executable, "-c", code]


def test_job_stdin_is_not_inherited():
    runner = JobRunner()
    job, err = runner.submit(
        "ws", ".", _py("import sys; print(repr(sys.stdin.read()))")
    )
    assert err is None
    done = _wait(runner, job["id"])
    assert done["status"] == "succeeded"
    assert "''" in done["log"]


def test_job_timeout_fails_the_job_and_frees_the_workspace():
    runner = JobRunner(timeout_sec=0.5)
    job, _ = runner.submit("ws", ".", _py("import time; time.sleep(30)"))
    done = _wait(runner, job["id"], timeout=15)
    assert done["status"] == "failed"
    assert "timed out" in done["log"].lower()
    again, err = runner.submit("ws", ".", _py("print('ok')"))
    assert err is None
    assert _wait(runner, again["id"])["status"] == "succeeded"


def test_job_table_keeps_only_recent_finished_jobs():
    runner = JobRunner(max_jobs=3)
    ids = []
    for i in range(5):
        job, _ = runner.submit(f"ws{i}", ".", _py("print('x')"))
        _wait(runner, job["id"])
        ids.append(job["id"])
    assert all(runner.get(j) is None for j in ids[:2])
    assert all(runner.get(j) is not None for j in ids[2:])


def test_job_log_is_capped_to_its_tail():
    runner = JobRunner()
    n = MAX_JOB_LOG_BYTES * 2
    job, _ = runner.submit(
        "ws", ".", _py(f"import sys; sys.stdout.write('a' * {n} + 'END')")
    )
    done = _wait(runner, job["id"])
    assert len(done["log"].encode()) <= MAX_JOB_LOG_BYTES + 200
    assert done["log"].endswith("END")
