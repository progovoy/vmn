"""Plan 28 N7: notes as data — note *signatures*, not text.

The fold masks each ``log_note`` text like a failure signature (numbers,
sizes, ids, paths) and keeps ``{sig: {count, last_at}}``, at most
:data:`~vmn_exp.core.note_sigs.MAX_SIGS` per run, in the index snapshot's
``note_sigs`` side table (``notes_of``), never on lean rows. ``notes ~
"sigterm"`` matches a run's signatures."""
import datetime
import json

import pytest
from vmn_exp.core.fold import fold_log
from vmn_exp.core.index import snapshot_of_folds
from vmn_exp.core.index_views import SIDE_TABLES
from vmn_exp.core.note_sigs import (
    MAX_SIG,
    MAX_SIGS,
    last_note_sig,
    note_minutes,
    note_signature,
)
from vmn_exp.core.query import ROW_FIELDS, filter_rows
from vmn_exp.core.query_extra import OFF_ROW_FIELDS, reads_off_row, rows_extra

APP = "trainer"


def _note(text, ts):
    return {"timestamp": ts, "type": "note", "text": text}


def _fold(*notes):
    log = [{"timestamp": "2026-10-24T10:00:00Z", "type": "create", "params": {}, "note": None}]
    return fold_log(log + list(notes))


def _snap(*runs):
    folds = []
    for idx, (verstr, notes) in enumerate(runs, 1):
        meta = {"verstr": verstr, "timestamp": f"2026-10-24T0{idx}:00:00Z",
                "code_verstr": verstr, "base_version": "0.0.1", "note": None}
        folds.append((idx, meta, _fold(*notes)))
    return snapshot_of_folds(APP, folds)


def test_a_note_signature_masks_what_differs_per_run():
    a = note_signature("Received SIGTERM at step 1200, saving 2.3 GiB to /ckpt/run-7/x.pt")
    b = note_signature("Received SIGTERM at step 87,  saving 0.4 GiB to /ckpt/run-9/y.pt")
    assert a == b == "Received SIGTERM at step <n>, saving <n> GiB to <path>"
    assert note_signature("retry 3 of 5 after OOMKilled") == "retry <n> of <n> after OOMKilled"
    assert len(note_signature("x" * 500)) == MAX_SIG
    assert len(json.dumps(note_signature("é\U0001f525" * 100))) <= MAX_SIG + 2
    assert note_signature("   ") is None
    assert note_signature(None) is None


def test_the_fold_counts_each_signature_and_keeps_its_last_time():
    snap = _snap(("a", [
        _note("Received SIGTERM at step 10", "2026-10-24T10:01:00Z"),
        _note("resumed from step 10", "2026-10-24T10:05:00Z"),
        _note("Received SIGTERM at step 40", "2026-10-24T10:09:30Z"),
    ]))
    assert snap.notes_of("a") == {
        "resumed from step <n>": {"count": 1, "last_at": "2026-10-24T10:05:00Z"},
        "Received SIGTERM at step <n>": {"count": 2, "last_at": "2026-10-24T10:09:30Z"},
    }
    assert last_note_sig(snap.notes_of("a")) == "Received SIGTERM at step <n>"


def test_signatures_stay_off_the_lean_rows():
    snap = _snap(("a", [_note("hello 1", "2026-10-24T10:01:00Z")]), ("b", []))
    assert "note_sigs" in SIDE_TABLES
    assert not {"note_sigs", "notes"} & set(snap.rows[0])
    assert snap.notes_of("b") is None
    assert snap.note_sigs == {"a": {"hello <n>": {"count": 1, "last_at": "2026-10-24T10:01:00Z"}}}


def test_at_most_eight_kept_the_most_frequent_then_the_most_recent():
    notes = [_note("frequent", f"2026-10-24T10:0{i}:00Z") for i in range(3)]
    notes += [_note(f"rare {chr(97 + i)}", f"2026-10-24T11:{i:02d}:00Z") for i in range(12)]
    got = _snap(("a", notes)).notes_of("a")
    assert len(got) == MAX_SIGS
    assert got["frequent"]["count"] == 3
    # The newest rare ones are kept, the older rare ones evicted.
    rare = sorted(s for s in got if s.startswith("rare"))
    assert rare == [f"rare {chr(97 + i)}" for i in range(5, 12)]
    assert last_note_sig(got) == "rare l"


def test_a_blank_or_malformed_note_folds_into_nothing():
    snap = _snap(("a", [_note("  ", "2026-10-24T10:01:00Z"),
                        {"timestamp": "t", "type": "note", "text": 3}]))
    assert snap.notes_of("a") is None


def test_the_persisted_value_reads_back_the_same_and_stays_small():
    """Plan 27 budgets <= 1.5 KB per run in published parts: a run's worst
    case signatures take at most 1 KB of it."""
    notes = [_note(f"{chr(97 + i)}" * 300 + " step 7", f"2026-10-24T10:{i:02d}:00.123456+00:00")
             for i in range(20)]
    notes += [_note("\U0001f525" * 100 + f" {chr(97 + i)}", f"2026-10-24T11:{i:02d}:00.123456+00:00")
              for i in range(4)]
    notes += [dict(notes[0], timestamp="2026-10-24T12:00:00.123456+00:00")] * 1000
    value = _snap(("a", notes)).notes_of("a")
    encoded = json.dumps(value, default=str)
    assert len(encoded.encode()) <= 1024
    decoded = json.loads(encoded)
    assert last_note_sig(decoded) == last_note_sig(value)
    assert note_minutes(decoded) == note_minutes(value)


def test_note_minutes_are_each_signatures_last_minute():
    value = {"x": {"count": 2, "last_at": "2026-10-24T10:01:30Z"},
             "y": {"count": 1, "last_at": "not a time"}}
    minute = datetime.datetime(2026, 10, 24, 10, 1, tzinfo=datetime.timezone.utc)
    assert note_minutes(value) == [int(minute.timestamp() // 60)]
    assert note_minutes(None) == []


@pytest.fixture
def evicted():
    return _snap(
        ("a", [_note("Received SIGTERM, releasing", "2026-10-24T10:01:00Z")]),
        ("b", [_note("OOMKilled, retry 2", "2026-10-24T10:02:00Z")]),
        ("c", []),
    )


def _verstrs(snap, text):
    return [r["verstr"] for r in filter_rows(list(snap.rows), text, extra=rows_extra(snap))]


def test_notes_queries_match_signatures(evicted):
    assert "notes" in ROW_FIELDS and "notes" in OFF_ROW_FIELDS
    assert reads_off_row('notes ~ "sigterm"')
    assert _verstrs(evicted, 'notes ~ "sigterm"') == ["a"]
    assert _verstrs(evicted, 'notes ~ "retry <n>"') == ["b"]
    assert _verstrs(evicted, "notes = null") == ["c"]
    assert _verstrs(evicted, 'not notes ~ "oom"') == ["a", "c"]
