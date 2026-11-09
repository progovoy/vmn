"""The median stopping rule, on synthetic metric series."""
from vmn_exp.core.sweep.early_stop import MedianStopper, median_should_stop, step_points


def _curve(values, start=1):
    return [(start + i, v) for i, v in enumerate(values)]


def test_points_without_a_step_are_numbered_in_log_order():
    points = [{"step": None, "value": 3.0}, {"step": None, "value": 2.0}]
    assert step_points(points) == [(1, 3.0), (2, 2.0)]
    assert step_points([{"step": 10, "value": 1.0}]) == [(10, 1.0)]


def test_non_finite_and_boolean_values_are_not_points():
    points = [
        {"step": 1, "value": float("nan")},
        {"step": 2, "value": True},
        {"step": 3, "value": float("inf")},
        {"step": 4, "value": 0.5},
    ]
    assert step_points(points) == [(4, 0.5)]


def test_a_trial_worse_than_the_median_at_its_step_is_stopped():
    others = [_curve([1.0, 0.8, 0.6]), _curve([1.1, 0.9, 0.7]), _curve([5.0, 5.0, 5.0])]
    own = _curve([3.0, 3.0, 3.0])
    assert median_should_stop(own, others, goal="min", min_iter=3)


def test_a_trial_better_than_the_median_keeps_running():
    others = [_curve([1.0, 0.8, 0.6]), _curve([3.0, 3.0, 3.0])]
    own = _curve([0.9, 0.5, 0.4])
    assert not median_should_stop(own, others, goal="min", min_iter=3)


def test_nothing_is_stopped_before_min_iter():
    others = [_curve([0.1, 0.1, 0.1, 0.1])]
    own = _curve([9.0, 9.0])
    assert not median_should_stop(own, others, goal="min", min_iter=3)


def test_the_comparison_is_at_the_trials_own_step():
    # Others only look good late; at step 2 the trial is still ahead.
    others = [_curve([1.0, 1.0, 0.1, 0.1]), _curve([1.0, 1.0, 0.1, 0.1])]
    own = _curve([0.9, 0.9])
    assert not median_should_stop(own, others, goal="min", min_iter=1)


def test_others_that_did_not_reach_the_step_do_not_count():
    others = [_curve([0.1])]
    own = _curve([5.0, 5.0, 5.0])
    assert not median_should_stop(own, others, goal="min", min_iter=3)


def test_min_trials_requires_enough_comparable_trials():
    others = [_curve([0.1, 0.1, 0.1])]
    own = _curve([5.0, 5.0, 5.0])
    assert median_should_stop(own, others, goal="min", min_iter=1, min_trials=1)
    assert not median_should_stop(own, others, goal="min", min_iter=1, min_trials=2)


def test_maximize_goal_flips_the_rule():
    others = [_curve([0.5, 0.7, 0.9]), _curve([0.6, 0.8, 0.9])]
    assert median_should_stop(_curve([0.1, 0.2, 0.3]), others, goal="max", min_iter=3)
    assert not median_should_stop(_curve([0.9, 0.95, 0.99]), others, goal="max", min_iter=3)


def test_best_so_far_is_what_is_compared():
    # A single noisy spike up does not stop a trial whose best is competitive.
    others = [_curve([1.0, 0.8, 0.6]), _curve([1.0, 0.8, 0.6])]
    own = _curve([0.9, 0.5, 4.0])
    assert not median_should_stop(own, others, goal="min", min_iter=3)


def _stopper(min_iter=2, min_trials=1):
    return MedianStopper({"metric": {"goal": "min"}, "early_terminate": {
        "min_iter": min_iter, "min_trials": min_trials, "check_interval_sec": 1}})


def test_a_check_judges_the_steps_logged_since_the_last_one():
    # Peers ended at step 4; the first check landed at step 6 (a slow poll).
    # A check at steps 2-4 would have stopped the trial: so does this one.
    others = [_curve([1.0, 0.9, 0.8, 0.7]), _curve([1.1, 1.0, 0.9, 0.8])]
    assert _stopper().should_stop(_curve([9.0] * 6), others)



def test_a_step_the_peers_reach_after_a_check_is_judged_by_the_next():
    stopper = _stopper()
    own = _curve([9.0] * 6)
    assert not stopper.should_stop(own, [_curve([1.0])] * 2)  # peers not at step 2 yet
    assert stopper.should_stop(own, [_curve([1.0] * 6)] * 2)
