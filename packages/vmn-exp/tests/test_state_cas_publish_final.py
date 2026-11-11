"""``publish_final_if_unfinished``: a run's final state replaces a stored one
only when that stored state is unfinished and of the same attempt, by one
conditional write on the stored version token."""
import yaml

from vmn_exp.core.state_cas import publish_final_if_unfinished
from vmn_exp.core.status import RUN_STATE_FILE

APP, VERSTR = "app", "0.0.1-dev.abc.0000001.r1"
FINAL = {"state": "finished", "attempt": "a1", "exit_code": 3}


class FakeSide:
    """One state file with a version token; ``on_load`` runs after a read."""

    def __init__(self, state=None):
        self.data = yaml.dump(state) if state is not None else None
        self.token = 0
        self.on_load = None

    def load_file_with_token(self, app_name, verstr, filename):
        assert (app_name, verstr, filename) == (APP, VERSTR, RUN_STATE_FILE)
        loaded = (self.data, self.token)
        if self.on_load:
            self.on_load, hook = None, self.on_load
            hook()
        return loaded

    def save_file_if_match(self, app_name, verstr, filename, data, etag=None):
        if etag != self.token:
            return False, None
        self.put(yaml.safe_load(data))
        return True, self.token

    def put(self, state):
        self.data, self.token = yaml.dump(state), self.token + 1

    def state(self):
        return yaml.safe_load(self.data)


def test_a_running_state_of_the_same_attempt_is_replaced_by_its_final_state():
    side = FakeSide({"state": "running", "attempt": "a1"})
    assert publish_final_if_unfinished(side, APP, VERSTR, FINAL) is True
    assert side.state() == FINAL


def test_a_state_finished_by_another_attempt_is_kept():
    theirs = {"state": "finished", "attempt": "b2", "exit_code": 0}
    side = FakeSide(theirs)
    assert publish_final_if_unfinished(side, APP, VERSTR, FINAL) is False
    assert side.state() == theirs


def test_another_attempts_running_state_is_never_ended():
    theirs = {"state": "running", "attempt": "b2"}
    side = FakeSide(theirs)
    assert publish_final_if_unfinished(side, APP, VERSTR, FINAL) is False
    assert side.state() == theirs


def test_a_local_running_state_is_never_published():
    stored = {"state": "running", "attempt": "a1"}
    side = FakeSide(stored)
    local = {"state": "running", "attempt": "a1", "beat": 2}
    assert publish_final_if_unfinished(side, APP, VERSTR, local) is False
    assert side.state() == stored


def test_a_concurrent_finisher_wins_the_race():
    side = FakeSide({"state": "running", "attempt": "a1"})
    winner = {"state": "finished", "attempt": "a1", "exit_code": 0}
    side.on_load = lambda: side.put(winner)
    assert publish_final_if_unfinished(side, APP, VERSTR, FINAL) is False
    assert side.state() == winner


def test_a_stored_state_without_an_attempt_key_counts_as_the_same_attempt():
    side = FakeSide({"state": "running"})
    assert publish_final_if_unfinished(side, APP, VERSTR, FINAL) is True
    assert side.state() == FINAL


def test_a_local_final_state_without_an_attempt_proves_no_identity():
    stored = {"state": "running"}
    side = FakeSide(stored)
    local = {"state": "finished", "exit_code": 1}
    assert publish_final_if_unfinished(side, APP, VERSTR, local) is False
    assert side.state() == stored
