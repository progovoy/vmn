"""A run its supervisor stopped on purpose (sweep early stopping) succeeded,
whatever code the child exited with; the real exit code is kept."""
from vmn_exp.core.status import FAILED, SUCCEEDED, derive_status


def test_a_stopped_early_run_succeeds_with_its_real_exit_code():
    state = {"state": "finished", "exit_code": 143, "stopped_early": True}
    assert derive_status(state) == SUCCEEDED
    assert state["exit_code"] == 143


def test_a_signalled_run_without_the_flag_still_fails():
    assert derive_status({"state": "finished", "exit_code": 143}) == FAILED
