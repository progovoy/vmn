"""Consumers read metric series through SeriesReader (plan 12 §5.5):
history ranges/thinning, resume steps and the log views."""
from vmn_exp.core.log import history_points, merged_log_view
from vmn_exp.sdk.steps import resume_next_step


def _m(step, ts, **values):
    entry = {"type": "metrics", "timestamp": f"2026-01-01T00:00:{ts:02d}Z", "values": values}
    if step is not None:
        entry["step"] = step
    return entry


LOG = [{"type": "create", "timestamp": "2026-01-01T00:00:00Z"}] + [
    _m(i, i + 1, loss=float(10 - i)) for i in range(10)
] + [{"type": "note", "timestamp": "2026-01-01T00:00:30Z", "text": "done"}]


def test_history_points_is_the_full_series_by_default():
    points = history_points(LOG, "loss")
    assert [p["step"] for p in points] == list(range(10))
    assert points[0] == {"step": 0, "ts": "2026-01-01T00:00:01Z", "value": 10.0}


def test_history_points_keeps_a_step_range():
    assert [p["step"] for p in history_points(LOG, "loss", step_range=(3, 5))] == [3, 4, 5]


def test_history_points_thins_to_max_points_keeping_the_ends():
    points = history_points(LOG, "loss", max_points=4)
    assert len(points) <= 4
    assert points[0]["step"] == 0 and points[-1]["step"] == 9


def test_history_points_of_an_unlogged_metric_is_empty():
    assert history_points(LOG, "acc") == []


def test_resume_next_step_is_past_the_highest_metric_step():
    assert resume_next_step(LOG + [_m(None, 40, lr=1.0)]) == 10
    assert resume_next_step(LOG[:1]) == 0


def test_merged_log_view_pages_the_log_with_its_total():
    view = merged_log_view(LOG, offset=10, limit=5)
    assert view["total"] == 12
    assert view["entries"] == LOG[10:12]


def test_merged_log_view_without_limit_is_the_rest():
    assert merged_log_view(LOG)["entries"] == LOG
