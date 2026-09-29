"""Rewinding a run: a ``{"type": "rewind", "step": N}`` log entry hides every
entry with a step past N written *before* it; entries written after it count.

Logs are append-only across writers and S3 segments, so a rewind cannot delete
history — every reader (the merged log, the fold, the incremental index fold,
the series) has to agree to skip it.
"""
import random

import pytest

from vmn_exp.core.fold import (
    apply_entries,
    fold_rewinds,
    fold_row,
    fold_values,
    needs_refold,
    new_fold,
)
from vmn_exp.core.log import experiment_row, latest_metrics, metric_series
from vmn_exp.core.rewind import create_rewind_entry, drop_rewound
from vmn_exp.storage.files import flatten_logs

META = {"verstr": "0.0.1-dev.aaa.bbb", "timestamp": "2026-01-01T00:00:00Z"}


def _m(ts, step, loss):
    return {"timestamp": ts, "type": "metrics", "step": step, "values": {"loss": loss}}


def _rw(ts, step):
    return {"timestamp": ts, "type": "rewind", "step": step}


def test_create_rewind_entry_is_timestamped():
    entry = create_rewind_entry(3)
    assert entry["type"] == "rewind"
    assert entry["step"] == 3
    assert entry["timestamp"]


def test_drop_rewound_hides_later_steps_written_before_the_marker():
    log = [_m("t1", 1, 1.0), _m("t2", 2, 0.9), _m("t3", 3, 0.8), _rw("t4", 1),
           _m("t5", 2, 0.5)]
    kept = drop_rewound(log)
    assert [(e["type"], e.get("step")) for e in kept] == [
        ("metrics", 1), ("rewind", 1), ("metrics", 2)]


def test_entries_without_a_step_survive_a_rewind():
    log = [{"timestamp": "t1", "type": "params", "params": {"lr": 0.1}},
           {"timestamp": "t2", "type": "metrics", "values": {"acc": 1.0}},
           _rw("t3", 0)]
    assert len(drop_rewound(log)) == 3


def test_repeated_rewinds_each_cut_what_came_before():
    log = [_m("a", s, float(s)) for s in range(1, 6)]  # 1..5
    log += [_rw("b", 2)] + [_m("c", s, 10.0 + s) for s in range(3, 8)]  # 3..7
    log += [_rw("d", 4)] + [_m("e", 5, 99.0)]
    series = metric_series(drop_rewound(log))["loss"]
    assert [(p["step"], p["value"]) for p in series] == [
        (1, 1.0), (2, 2.0), (3, 13.0), (4, 14.0), (5, 99.0)]


def test_fold_log_ignores_rewound_entries():
    log = [_m("t1", 1, 1.0), _m("t2", 5, 0.1), _rw("t3", 1)]
    assert latest_metrics(log) == {"loss": 1.0}
    row = experiment_row(1, META, log)
    assert row["metrics"] == {"loss": 1.0}


def test_flatten_logs_drops_rewound_entries_across_writers():
    logs = {
        "old": [_m("t1", 1, 1.0), _m("t3", 2, 0.5)],
        "new": [_rw("t4", 1), _m("t5", 2, 0.7)],
    }
    merged = flatten_logs(logs)
    assert [(e["type"], e.get("step"), e.get("values")) for e in merged] == [
        ("metrics", 1, {"loss": 1.0}), ("rewind", 1, None),
        ("metrics", 2, {"loss": 0.7})]


def test_incremental_fold_learns_a_rewind_and_asks_for_a_refold():
    fold = new_fold()
    apply_entries(fold, "old", 0, [_m("t1", 1, 1.0), _m("t2", 2, 0.5)])
    assert not needs_refold(fold)
    apply_entries(fold, "new", 0, [_rw("t3", 1)])
    assert needs_refold(fold)

    again = new_fold(fold_rewinds(fold))
    apply_entries(again, "old", 0, [_m("t1", 1, 1.0), _m("t2", 2, 0.5)])
    apply_entries(again, "new", 0, [_rw("t3", 1)])
    assert not needs_refold(again)
    assert fold_values(again, "metrics") == {"loss": 1.0}


def test_a_known_rewind_filters_entries_folded_after_it():
    """An old writer's late-arriving chunk still predates the marker."""
    fold = new_fold()
    apply_entries(fold, "new", 0, [_rw("t3", 1), _m("t4", 2, 0.7)])
    assert needs_refold(fold)  # a first sight of a rewind always refolds
    fold = new_fold(fold_rewinds(fold))
    apply_entries(fold, "new", 0, [_rw("t3", 1), _m("t4", 2, 0.7)])
    apply_entries(fold, "old", 0, [_m("t1", 1, 1.0), _m("t2", 2, 0.5)])
    assert fold_values(fold, "metrics") == {"loss": 0.7}
    assert not needs_refold(fold)


def _random_entry(rng):
    ts = f"2026-01-01T00:00:{rng.randint(0, 9):02d}Z"
    roll = rng.random()
    if roll < 0.15:
        return _rw(ts, rng.randint(0, 6))
    if roll < 0.25:
        return {"timestamp": ts, "type": "params", "params": {"lr": rng.random()}}
    entry = {"timestamp": ts, "type": "metrics",
             "values": {rng.choice(["loss", "acc"]): rng.random()}}
    if rng.random() < 0.8:
        entry["step"] = rng.randint(0, 9)
    return entry


def _chunked_fold(rng, writers, fold):
    cursors = {w: 0 for w in writers}
    while any(cursors[w] < len(writers[w]) for w in writers):
        writer = rng.choice([w for w in writers if cursors[w] < len(writers[w])])
        chunk = writers[writer][cursors[writer] : cursors[writer] + rng.randint(1, 4)]
        apply_entries(fold, writer, cursors[writer], chunk)
        cursors[writer] += len(chunk)
    return fold


@pytest.mark.parametrize("seed", range(60))
def test_incremental_fold_with_rewinds_matches_the_merged_log(seed):
    rng = random.Random(seed)
    writers = {w: [_random_entry(rng) for _ in range(rng.randint(0, 20))]
               for w in ("", "w0", "w1")}

    fold = _chunked_fold(rng, writers, new_fold())
    if needs_refold(fold):
        fold = _chunked_fold(rng, writers, new_fold(fold_rewinds(fold)))
    assert not needs_refold(fold)

    expected = experiment_row(3, META, flatten_logs(writers))
    assert fold_row(3, META, fold) == expected
    schema = {"loss": {"goal": "min"}, "acc": {"goal": "max"}}
    expected = experiment_row(3, META, flatten_logs(writers), schema=schema)
    assert fold_row(3, META, fold, schema=schema) == expected


# -- best-value summaries ------------------------------------------------------

MIN_LOSS = {"loss": {"goal": "min"}}


def test_rewound_entries_do_not_count_toward_min_and_max():
    log = [_m("t1", 1, 1.0), _m("t2", 2, 0.1), _m("t3", 3, 9.0), _rw("t4", 1),
           _m("t5", 2, 0.5)]
    row = experiment_row(1, META, log, schema=MIN_LOSS)
    assert row["metrics"]["loss"] == 0.5
    assert row["metric_summary"]["loss"]["min"] == 0.5
    assert row["metric_summary"]["loss"]["max"] == 1.0


def test_the_refolded_index_fold_forgets_rewound_extrema():
    old = [_m("t1", 1, 1.0), _m("t2", 2, 0.1)]
    new = [_rw("t3", 1), _m("t4", 2, 0.5)]
    fold = new_fold()
    apply_entries(fold, "old", 0, old)
    apply_entries(fold, "new", 0, new)
    assert needs_refold(fold)
    fold = new_fold(fold_rewinds(fold))
    apply_entries(fold, "old", 0, old)
    apply_entries(fold, "new", 0, new)
    row = fold_row(1, META, fold, schema=MIN_LOSS)
    assert row["metrics"]["loss"] == 0.5
    merged = flatten_logs({"old": old, "new": new})
    assert row == experiment_row(1, META, merged, schema=MIN_LOSS)
