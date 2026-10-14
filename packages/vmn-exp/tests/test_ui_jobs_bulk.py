"""A bulk job (plan 23 S4): resolved when it starts, acted on in batches of
500, its ``progress`` visible through the job."""
import time

from vmn_exp.ui.bulk_actions import BulkSpec
from vmn_exp.ui.jobs import JobRunner


def _wait(runner, job_id):
    deadline = time.time() + 30
    while time.time() < deadline:
        job = runner.get(job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_a_bulk_job_resolves_at_start_and_acts_in_batches():
    runner, batches = JobRunner(), []
    resolved = []
    job, err = runner.submit_bulk(
        "ws", ["exp_archive", "my_app"],
        lambda: resolved.append(1) or [f"v{i}" for i in range(1201)],
        lambda batch: batches.append(len(batch)) or "ok",
    )
    assert err is None and job["progress"] == {"done": 0, "total": None}
    job = _wait(runner, job["id"])
    assert job["status"] == "succeeded"
    assert batches == [500, 500, 201]
    assert job["progress"] == {"done": 1201, "total": 1201}
    assert resolved == [1]


def test_a_failed_batch_fails_the_job_with_the_progress_so_far():
    def act(batch):
        if batch[0] == "v500":
            raise RuntimeError("boom")
        return "ok"

    runner = JobRunner()
    job, _ = runner.submit_bulk("ws", ["x"], lambda: [f"v{i}" for i in range(1200)], act)
    job = _wait(runner, job["id"])
    assert job["status"] == "failed" and "boom" in job["log"]
    assert job["progress"] == {"done": 500, "total": 1200}


def test_git_commands_archive_a_batch_at_once_and_tag_run_by_run():
    archive, _ = BulkSpec.build("exp_archive", "root/svc", {"scope": "j"})
    assert archive.commands(["a", "b"]) == [
        ["vmn-exp", "experiment", "archive", "root/svc", "a", "b"]]
    tag, _ = BulkSpec.build("exp_tag", "my_app", {"scope": "j", "set": {"k": "v"}, "remove": ["o"]})
    assert tag.commands(["a", "b"]) == [
        ["vmn-exp", "experiment", "tag", "my_app", "a", "k=v", "--remove", "o"],
        ["vmn-exp", "experiment", "tag", "my_app", "b", "k=v", "--remove", "o"],
    ]
