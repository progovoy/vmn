"""The index's chunked fold of ``features``/``intent``/``hypothesis`` agrees
with the direct fold of the merged log.

The index folds each writer's entries in arbitrary chunks keyed by
``(timestamp, writer, position)``; ``fold_log`` folds the merged log (writers
by name, stably sorted by timestamp) by position. Both must pick the same
features entry, intent and hypothesis, and so build the same row.
"""
import random

import pytest
from vmn_exp.core.fold import (
    apply_entries,
    fold_features,
    fold_hypothesis,
    fold_intent,
    fold_log,
    fold_row,
    new_fold,
)

META = {"verstr": "0.0.1-dev.a", "timestamp": "2026-01-01T00:00:00Z"}
EMAILS = ["a@x.io", "b@x.io", "", None]


def _flatten(logs_by_writer):
    """The reference merge (mirrors the storage's flatten_logs)."""
    entries = []
    for writer in sorted(logs_by_writer):
        entries.extend(logs_by_writer[writer])
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries


def _random_entry(rng, serial):
    ts = f"2026-01-01T00:00:{rng.randint(0, 6):02d}Z"  # plenty of timestamp ties
    kind = rng.choice(["features", "features", "intent", "create", "metrics"])
    if kind == "features":
        version = rng.choice([1, 1, 2, 3, "2", None])
        author = {"writer": f"w{serial}", "git_user_email": rng.choice(EMAILS)}
        return {"timestamp": ts, "type": "features", "features_version": version,
                "source": "capture", "author": author, "changed": {"files": [f"f{serial}.py"]}}
    if kind == "intent":
        text = rng.choice([f"intent {serial}", f"intent {serial}", "", None])
        return {"timestamp": ts, "type": "intent", "text": text, "source": "user"}
    if kind == "create":
        entry = {"timestamp": ts, "type": "create", "params": {}, "note": f"n{serial}"}
        if rng.random() < 0.6:
            entry["hypothesis"] = rng.choice([f"h{serial}", "", 3])
        return entry
    return {"timestamp": ts, "type": "metrics", "values": {"loss": rng.random()}}


def _chunked_fold(rng, writers):
    fold = new_fold()
    cursors = {w: 0 for w in writers}
    while any(cursors[w] < len(writers[w]) for w in writers):
        writer = rng.choice([w for w in writers if cursors[w] < len(writers[w])])
        take = rng.randint(1, 3)
        chunk = writers[writer][cursors[writer]: cursors[writer] + take]
        apply_entries(fold, writer, cursors[writer], chunk)
        cursors[writer] += len(chunk)
    return fold


@pytest.mark.parametrize("seed", range(60))
def test_chunked_index_fold_matches_the_merged_log_fold(seed):
    rng = random.Random(seed)
    serial = iter(range(10_000))
    writers = {w: [_random_entry(rng, next(serial)) for _ in range(rng.randint(0, 12))]
               for w in ("", "w0", "w1")}
    chunked = _chunked_fold(rng, writers)
    direct = fold_log(_flatten(writers))
    assert fold_features(chunked) == fold_features(direct)
    assert fold_intent(chunked) == fold_intent(direct)
    assert fold_hypothesis(chunked) == fold_hypothesis(direct)
    a, b = fold_row(1, META, chunked), fold_row(1, META, direct)
    assert (a["author"], a["has_intent"]) == (b["author"], b["has_intent"])
