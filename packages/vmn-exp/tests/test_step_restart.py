"""A metric's steps going back without a rewind: the first such write."""
from vmn_exp.core.step_restart import StepRestarts


def _points(steps):
    return [{"step": s, "value": 0.0} for s in steps]


def test_monotone_steps_are_no_restart():
    restarts = StepRestarts()
    restarts.add("loss", _points([0, 1, 2, 5]))
    assert restarts.found == {}


def test_a_step_going_back_is_marked_at_its_write():
    restarts = StepRestarts()
    restarts.add("best", _points(list(range(121)) + list(range(6))))
    assert restarts.found == {"best": {"write": 122, "from": 120, "to": 0}}


def test_a_repeated_step_is_a_restart_too():
    restarts = StepRestarts()
    restarts.add("loss", _points([0, 1, 1]))
    assert restarts.found == {"loss": {"write": 3, "from": 1, "to": 1}}


def test_growth_across_adds_and_step_less_points():
    restarts = StepRestarts()
    restarts.add("loss", _points([0, None, 3]))
    restarts.add("loss", _points([None, 4]))
    assert restarts.found == {}
    restarts.add("loss", _points([2, 0]))
    assert restarts.found == {"loss": {"write": 6, "from": 4, "to": 2}}


def test_only_the_first_restart_is_kept():
    restarts = StepRestarts()
    restarts.add("loss", _points([5, 0, 9, 1]))
    assert restarts.found == {"loss": {"write": 2, "from": 5, "to": 0}}
