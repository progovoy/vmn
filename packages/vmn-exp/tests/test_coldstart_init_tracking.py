"""``init_tracking``: the cold-start init, local-only unless asked to push.

Unit tests on fakes: no git, no Docker.
"""
import pytest

from vmn_exp.gitmode.coldstart import init_tracking


class FakeBackend:
    def __init__(self):
        self.pushes = 0

    def push(self, tags=()):
        self.pushes += 1

    def check_for_outgoing_changes(self):
        return None


class FakeVcs:
    def __init__(self, events):
        self.backend = FakeBackend()
        self._events = events

    def ensure_on_branch(self):
        self._events.append("ensure_on_branch")


def _pushing_init(events):
    def init(vcs, extra_optional=None):
        events.append("init")
        vcs.backend.push()
        return 0, True

    return init


def test_push_false_never_calls_backend_push():
    events = []
    vcs = FakeVcs(events)

    assert init_tracking(vcs, _pushing_init(events), push=False) == (0, True)

    assert vcs.backend.pushes == 0


def test_push_true_leaves_the_backend_untouched():
    events = []
    vcs = FakeVcs(events)

    init_tracking(vcs, _pushing_init(events), push=True)

    assert vcs.backend.pushes == 1
    assert "push" not in vcs.backend.__dict__


def test_push_is_restored_after_init_even_when_init_raises():
    vcs = FakeVcs([])

    def failing_init(vcs, extra_optional=None):
        raise RuntimeError("init failed")

    with pytest.raises(RuntimeError):
        init_tracking(vcs, failing_init, push=False)

    vcs.backend.push()
    assert vcs.backend.pushes == 1
    assert "push" not in vcs.backend.__dict__


def test_a_detached_head_is_put_on_its_branch_before_init():
    events = []
    vcs = FakeVcs(events)

    init_tracking(vcs, _pushing_init(events), push=False)

    assert events == ["ensure_on_branch", "init"]
