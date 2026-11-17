"""The UI job runner on injected processes, ids and a thread starter (plan 44
G5): no real child process, no real thread, no polling."""
import subprocess
import sys
import threading

import pytest

from fakes.processes import HANG, FakeProcesses
from fakes.random import FakeRandom
from vmn_exp.ui.jobs import JobRunner

STAMP = ["vmn", "stamp", "--release-mode=patch", "app"]


def _done(argv, code=0, out="", err=""):
    return subprocess.CompletedProcess(argv, code, stdout=out, stderr=err)


def _inline(target, *args):
    target(*args)


def _runner(script, start_thread=_inline, **kwargs):
    processes = FakeProcesses(script)
    runner = JobRunner(processes=processes, random=FakeRandom(), start_thread=start_thread, **kwargs)
    return runner, processes


def test_submit_runs_the_command_and_records_exit_code_and_log():
    runner, processes = _runner({tuple(STAMP): _done(STAMP, 3, "out\n", "err\n")})
    submitted, err = runner.submit("ws", "/repo", STAMP)
    assert err is None
    job = runner.get(submitted["id"])
    assert (job["status"], job["exit_code"], job["log"]) == ("failed", 3, "out\nerr\n")
    assert processes.calls[0][0] == STAMP and processes.calls[0][1]["cwd"] == "/repo"


def test_job_ids_come_from_the_given_random():
    runner, _ = _runner({tuple(STAMP): _done(STAMP)})
    random = FakeRandom()
    first, _ = runner.submit("ws", "/repo", STAMP)
    assert first["id"] == random.hex_id()


def test_timeout_fails_the_job_with_exit_code_minus_one_and_frees_the_workspace():
    runner, processes = _runner({tuple(STAMP): HANG}, timeout_sec=7)
    submitted, _ = runner.submit("ws", "/repo", STAMP)
    job = runner.get(submitted["id"])
    assert (job["status"], job["exit_code"]) == ("failed", -1)
    assert "timed out after 7s" in job["log"]
    assert processes.calls[0][1]["timeout"] == 7
    assert runner.submit("ws", "/repo", STAMP)[1] is None


def test_second_submit_in_a_busy_workspace_is_refused():
    held = []
    runner, _ = _runner({}, start_thread=lambda target, *args: held.append((target, args)))
    runner.submit("ws", "/repo", STAMP)
    assert runner.submit("ws", "/repo", STAMP) == (None, "Another action is already running in this workspace")
    assert runner.submit("other", "/repo", STAMP)[1] is None


def test_missing_console_script_falls_back_to_python_dash_m():
    fallback = [sys.executable, "-m", "version_stamp.cli"] + STAMP[1:]
    runner, processes = _runner({tuple(fallback): _done(fallback, 0, "stamped")})
    submitted, _ = runner.submit("ws", "/repo", STAMP)
    assert runner.get(submitted["id"])["log"] == "stamped"
    assert [argv for argv, _ in processes.calls] == [STAMP, fallback]


def test_job_stdin_is_closed():
    runner, processes = _runner({tuple(STAMP): _done(STAMP)})
    runner.submit("ws", "/repo", STAMP)
    assert processes.calls[0][1]["stdin"] is subprocess.DEVNULL


def test_finished_jobs_beyond_max_jobs_are_evicted_oldest_first():
    runner, _ = _runner({tuple(STAMP): _done(STAMP)}, max_jobs=2)
    ids = [runner.submit(f"ws{n}", "/repo", STAMP)[0]["id"] for n in range(3)]
    assert runner.get(ids[0]) is None
    assert [runner.get(job_id)["id"] for job_id in ids[1:]] == ids[1:]


def test_wait_returns_the_job_once_it_has_finished():
    runner, _ = _runner({tuple(STAMP): _done(STAMP, 0, "stamped")})
    submitted, _ = runner.submit("ws", "/repo", STAMP)
    job = runner.wait(submitted["id"], timeout=0)
    assert (job["status"], job["log"]) == ("succeeded", "stamped")


def test_wait_on_a_job_still_running_times_out_loudly():
    held = []
    runner, _ = _runner({tuple(STAMP): _done(STAMP)}, start_thread=lambda target, *args: held.append((target, args)))
    submitted, _ = runner.submit("ws", "/repo", STAMP)
    with pytest.raises(TimeoutError):
        runner.wait(submitted["id"], timeout=0)
    target, args = held.pop()
    target(*args)
    assert runner.wait(submitted["id"], timeout=0)["status"] == "succeeded"


def test_wait_returns_an_in_process_job_once_it_has_failed():
    runner, _ = _runner({})
    submitted, _ = runner.submit_call("ws", ["note"], lambda: 1 / 0)
    assert runner.wait(submitted["id"], timeout=0)["status"] == "failed"


class _ResubmitOnFinish(threading.Event):
    """A job's finished event that resubmits to the job's workspace the moment
    it is set, as a caller woken by ``wait()`` may; keeps the refusal."""

    def __init__(self, resubmit):
        super().__init__()
        self._resubmit, self.refusal = resubmit, "never finished"

    def set(self):
        self.refusal = self._resubmit()[1]
        super().set()


def _refusal_on_finish(submit_job):
    """The refusal a resubmit to the workspace gets as its job finishes."""
    spies = []

    def start_first_inline(target, workspace, job):
        if not spies:  # the resubmitted job is never started
            spies.append(_ResubmitOnFinish(lambda: runner.submit(workspace, "/repo", STAMP)))
            job.finished = spies[0]
            target(workspace, job)

    runner, _ = _runner({tuple(STAMP): _done(STAMP)}, start_thread=start_first_inline)
    submit_job(runner)
    return spies[0].refusal


@pytest.mark.parametrize("submit_job", [
    lambda runner: runner.submit("ws", "/repo", STAMP),
    lambda runner: runner.submit_call("ws", ["note"], lambda: "ok"),
    lambda runner: runner.submit_call("ws", ["note"], lambda: 1 / 0),
], ids=["command", "call", "failing-call"])
def test_a_finished_job_has_already_freed_its_workspace(submit_job):
    assert _refusal_on_finish(submit_job) is None
