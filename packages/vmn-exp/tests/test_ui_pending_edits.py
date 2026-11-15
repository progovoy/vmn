"""A store edit whose upload failed is pending, not lost (plan 40 C16, owner
answer of 2026-11-11): the next action on the workspace first retries the
upload, and the failed job says the edit is pending until it ships.

Pure unit: the edit storage is an in-memory fake.
"""
import pytest

from vmn_exp.ui.pending_edits import PendingEditError, ship_pending_first


class _Buffer:
    """An edit storage holding *pending* unshipped lines."""

    def __init__(self, pending=False, ship_error=None):
        self.pending, self.ship_error, self.calls = pending, ship_error, []

    def has_pending(self):
        return self.pending

    def ship_pending(self):
        self.calls.append("ship")
        if self.ship_error is not None:
            raise self.ship_error
        self.pending = False


def _perform(storage, error=None, leaves_pending=False):
    def perform():
        storage.calls.append("perform")
        if error is not None:
            storage.pending = leaves_pending
            raise error
        return "done"
    return perform


def test_the_next_action_first_ships_the_pending_upload():
    storage = _Buffer(pending=True)
    assert ship_pending_first(storage, _perform(storage)) == "done"
    assert storage.calls == ["ship", "perform"]


def test_nothing_pending_runs_the_action_alone():
    storage = _Buffer()
    assert ship_pending_first(storage, _perform(storage)) == "done"
    assert storage.calls == ["perform"]


def test_an_action_behind_a_pending_upload_that_fails_again_does_not_run():
    storage = _Buffer(pending=True, ship_error=ConnectionError("out of reach"))
    with pytest.raises(PendingEditError) as raised:
        ship_pending_first(storage, _perform(storage))
    assert storage.calls == ["ship"]
    assert "An earlier edit is still pending" in str(raised.value)
    assert "out of reach" in str(raised.value)


def test_a_failed_edit_left_in_the_buffer_says_it_is_pending():
    storage = _Buffer()
    perform = _perform(storage, ConnectionError("out of reach"), leaves_pending=True)
    with pytest.raises(PendingEditError) as raised:
        ship_pending_first(storage, perform)
    assert "out of reach" in str(raised.value)
    assert "pending until it ships" in str(raised.value)


def test_a_failed_edit_with_nothing_buffered_fails_as_before():
    storage = _Buffer()
    error = LookupError("Experiment 'v' not found for app")
    with pytest.raises(LookupError) as raised:
        ship_pending_first(storage, _perform(storage, error))
    assert raised.value is error


def test_a_storage_without_a_buffer_runs_the_action_alone():
    assert ship_pending_first(object(), lambda: "done") == "done"
