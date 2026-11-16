"""Waiting for a ui job in a test: on the job's own finished signal
(``JobRunner.wait``), not by polling against a wall-clock deadline that a
loaded machine can miss. The bound only makes a real hang fail loudly."""

HANG_SEC = 600


def wait_job(runner, job_id):
    """*job_id*'s job dict once *runner* has finished it."""
    return runner.wait(job_id, timeout=HANG_SEC)


def wait_job_http(client, job_id):
    """*job_id*'s job as ``GET /api/v1/jobs/<id>`` shows it once finished."""
    wait_job(client.app.state.jobs, job_id)
    return client.get(f"/api/v1/jobs/{job_id}").json()
