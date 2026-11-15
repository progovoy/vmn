"""An in-process job's call is bounded by the job timeout (plan 40 C16).

Pure unit: the thread starter is a fake that runs the call at once or holds
it, so nothing sleeps and no thread is started.
"""
from vmn_exp.ui.job_calls import run_bounded


def _run_now(target):
    target()


def test_a_call_that_returns_in_time_gives_its_result():
    outcome = run_bounded(lambda: "tagged", 0, _run_now)
    assert not outcome.timed_out
    assert outcome.value == "tagged" and outcome.error is None


def test_a_call_that_raises_gives_its_error():
    def call():
        raise RuntimeError("not found")

    outcome = run_bounded(call, 0, _run_now)
    assert not outcome.timed_out
    assert str(outcome.error) == "not found"


def test_a_call_past_the_timeout_reports_timed_out_and_keeps_running():
    held = []
    outcome = run_bounded(lambda: "late", 0, held.append)
    assert outcome.timed_out
    assert len(held) == 1  # started, never cancelled
    assert not outcome.returned.is_set()


def test_the_returned_event_is_set_when_the_late_call_ends():
    held = []
    outcome = run_bounded(lambda: "late", 0, held.append)
    held[0]()
    assert outcome.returned.is_set()
    assert outcome.value is None  # a timed-out outcome never takes the late value
