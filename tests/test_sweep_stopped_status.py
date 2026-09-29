"""A run its supervisor stopped on purpose (sweep early stopping) succeeded,
whatever code the child exited with; the real exit code is kept. The run
state's ``end_reason`` is the one record of why it ended."""
from vmn_exp.core.status import FAILED, STOPPED, SUCCEEDED, derive_status, status_fields


def test_a_stopped_run_succeeds_with_its_real_exit_code():
    state = {"state": "finished", "exit_code": 143, "end_reason": STOPPED}
    assert derive_status(state) == SUCCEEDED
    assert state["exit_code"] == 143


def test_a_signalled_run_without_an_end_reason_still_fails():
    assert derive_status({"state": "finished", "exit_code": 143}) == FAILED


def test_the_status_payload_carries_the_end_reason():
    stopped = {"state": "finished", "exit_code": 143, "end_reason": STOPPED}
    assert status_fields(stopped)["end_reason"] == STOPPED
    assert status_fields({"state": "finished", "exit_code": 0})["end_reason"] is None
