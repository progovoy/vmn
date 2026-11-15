"""``start_run(run_id=...)`` on a run the store does not hold: the error says
that ``run_id=`` reopens and points at ``create_run`` (plan 41 D6)."""
import pytest

from vmn_exp.sdk import resume


class _FakeStorage:
    """Answers ``exists`` from a fixed set; nothing else is touched."""

    def __init__(self, verstrs=()):
        self._verstrs = set(verstrs)

    def exists(self, app_name, verstr):
        return verstr in self._verstrs


def _unknown_run_error(from_env):
    with pytest.raises(ValueError) as excinfo:
        resume.existing_run(_FakeStorage(), "app", "my-name", from_env)
    return str(excinfo.value)


def test_unknown_run_id_error_points_at_create_run():
    message = _unknown_run_error(from_env=False)
    assert "start_run(run_id=...) reopens an existing run" in message
    assert "create_run(run_id=...)" in message
    assert "name=" in message


def test_unknown_env_run_id_error_names_the_env_var():
    message = _unknown_run_error(from_env=True)
    assert "VMN_RESUME_RUN_ID names a run that does not exist in this store" in message
    assert "create_run" not in message


def test_error_still_starts_with_cannot_resume_run():
    for from_env in (False, True):
        assert _unknown_run_error(from_env).startswith(
            "Cannot resume run 'my-name' of 'app': no such experiment")


def test_existing_run_returns_the_verstr_unchanged():
    storage = _FakeStorage({"1.2.0"})
    assert resume.existing_run(storage, "app", "1.2.0", from_env=False) == "1.2.0"
