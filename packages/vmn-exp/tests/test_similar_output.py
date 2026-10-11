"""How ``vmn-exp similar`` and the submission hint print a similar run: one
line per result, ages a person reads at a glance, and the hint's summary of
the closest runs."""
import datetime

from vmn_exp.cli.similar_output import age, hint_lines, item_line

NOW = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)


def _ago(**delta):
    return (NOW - datetime.timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _item(verstr="0.0.1-dev.a.b", **fields):
    item = {"app": "app", "verstr": verstr, "score": 0.8765, "author": "alice@x.io",
            "timestamp": _ago(days=21), "status": "succeeded", "group_size": 1,
            "goal": {"metric": "val_loss", "goal": "min", "value": 0.31234},
            "reasons": ["same dataset imagenet@3", "1 shared function: train_step"]}
    item.update(fields)
    return item


def test_age_reads_in_the_largest_whole_unit():
    assert age(_ago(seconds=5), NOW) == "5s ago"
    assert age(_ago(minutes=3), NOW) == "3m ago"
    assert age(_ago(hours=5), NOW) == "5h ago"
    assert age(_ago(days=2), NOW) == "2d ago"
    assert age(_ago(days=21), NOW) == "3w ago"
    assert age(_ago(days=65), NOW) == "2mo ago"
    assert age(_ago(days=800), NOW) == "2y ago"


def test_an_unknown_or_future_time_reads_plainly():
    assert age(None, NOW) == "-"
    assert age("not a time", NOW) == "-"
    assert age(_ago(seconds=-30), NOW) == "0s ago"


def test_a_result_line_has_score_author_age_status_goal_and_reasons():
    assert item_line(_item(), now=NOW) == (
        "0.0.1-dev.a.b  0.88  alice@x.io  3w ago  succeeded  val_loss=0.3123"
        "  — same dataset imagenet@3, 1 shared function: train_step"
    )


def test_a_group_counts_its_other_runs_and_all_apps_names_the_app():
    line = item_line(_item(app="other/svc", group_size=3), with_app=True, now=NOW)
    assert line.startswith("other/svc/0.0.1-dev.a.b  0.88  ")
    assert line.endswith("  (+2 runs)")
    assert item_line(_item(group_size=2), now=NOW).endswith("  (+1 run)")


def test_missing_author_goal_and_reasons_leave_placeholders():
    line = item_line(_item(author=None, goal=None, reasons=[]), now=NOW)
    assert line == "0.0.1-dev.a.b  0.88  -  3w ago  succeeded  —"


def test_the_hint_names_the_best_run_on_the_goal_then_the_others():
    closest = _item("v1", goal={"metric": "val_loss", "goal": "min", "value": 0.5})
    best = _item("v2", author="bob@x.io", timestamp=_ago(days=2), reasons=["same branch main"],
                 goal={"metric": "val_loss", "goal": "min", "value": 0.31})
    lines = hint_lines([closest, best], now=NOW)
    assert lines == [
        "2 similar runs: best val_loss=0.31 — v2 by bob@x.io, 2d ago (same branch main)",
        "  v1 by alice@x.io, 3w ago (same dataset imagenet@3, 1 shared function: train_step)",
    ]


def test_without_a_goal_the_hint_leads_with_the_closest_run():
    lines = hint_lines([_item("v1", goal=None, author=None, reasons=[])], now=NOW)
    assert lines == ["1 similar run: closest — v1, 3w ago"]
    assert hint_lines([], now=NOW) == []
