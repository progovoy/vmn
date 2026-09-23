"""The incremental fold agrees with the full ``experiment_row`` recompute.

``experiment_row`` folds a log that ``flatten_logs`` built: the legacy
``log.yml`` entries first, then each writer's entries (writers by name, file
order), stably sorted by timestamp. The incremental fold sees the same entries
in arbitrary chunks — per writer, in file order — and must end up identical.
"""
import random

import pytest

from version_stamp.core.experiment_fold import (
    apply_entries,
    fold_row,
    new_fold,
)
from version_stamp.core.experiment_log import experiment_row

META = {"verstr": "0.0.1-dev.aaa.bbb", "timestamp": "2026-01-01T00:00:00Z"}


def _flatten(logs_by_writer):
    """The reference merge (mirrors snapshot_storage_files.flatten_logs)."""
    entries = []
    for writer in sorted(logs_by_writer):
        entries.extend(logs_by_writer[writer])
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries


def _random_entry(rng):
    ts = f"2026-01-01T00:00:{rng.randint(0, 9):02d}Z"  # plenty of timestamp ties
    kind = rng.choice(["metrics", "metrics", "metrics", "params", "create", "note"])
    if kind == "metrics":
        values = {k: rng.choice([rng.random(), float("nan"), 3]) for k in
                  rng.sample(["loss", "acc", "lr", "epochs"], rng.randint(1, 3))}
        entry = {"timestamp": ts, "type": "metrics", "values": values}
        if rng.random() < 0.2:
            del entry["values"]  # a metrics entry without values still dates last_metric_at
        return entry
    if kind in ("params", "create"):
        params = {k: rng.choice([0.1, 7, "adam", True, float("nan"), None]) for k in
                  rng.sample(["lr", "opt", "epochs", "verbose", "missing"], rng.randint(1, 3))}
        entry = {"timestamp": ts, "type": kind, "params": params}
        if kind == "create":
            entry["note"] = rng.choice([None, "first", "second"])
        return entry
    return {"timestamp": ts, "type": "note", "text": "hi"}


def _same(a, b):
    """Row equality that treats NaN == NaN (a NaN metric is a legitimate value)."""
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return a == b


@pytest.mark.parametrize("seed", range(60))
def test_incremental_fold_matches_full_recompute(seed):
    rng = random.Random(seed)
    writers = {"": [], "w0": [], "w1": []}
    for writer in writers:
        n = rng.randint(0, 6) if writer == "" else rng.randint(0, 25)
        writers[writer] = [_random_entry(rng) for _ in range(n)]

    fold = new_fold()
    cursors = {w: 0 for w in writers}
    # Feed each writer's entries in random-sized chunks, writers interleaved.
    while any(cursors[w] < len(writers[w]) for w in writers):
        writer = rng.choice([w for w in writers if cursors[w] < len(writers[w])])
        take = rng.randint(1, 4)
        chunk = writers[writer][cursors[writer] : cursors[writer] + take]
        apply_entries(fold, writer, cursors[writer], chunk)
        cursors[writer] += len(chunk)

    expected = experiment_row(3, META, _flatten(writers))
    assert _same(fold_row(3, META, fold), expected)


def test_create_note_is_the_first_create_entry():
    fold = new_fold()
    apply_entries(fold, "w", 0, [
        {"timestamp": "t2", "type": "create", "note": "later"},
    ])
    apply_entries(fold, "a", 0, [
        {"timestamp": "t1", "type": "create", "note": "earliest"},
    ])
    assert fold_row(1, META, fold, with_create_note=True)["create_note"] == "earliest"


def test_empty_fold_is_the_empty_log_row():
    assert fold_row(1, META, new_fold()) == experiment_row(1, META, [])
