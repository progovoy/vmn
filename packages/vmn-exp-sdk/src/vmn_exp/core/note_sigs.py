#!/usr/bin/env python3
"""A run's notes as data (plan 28 N7): *signatures*, not text.

Each ``note`` entry's text is masked like a failure signature
(:func:`~vmn_exp.core.text_mask.mask`: numbers, sizes, ids, paths) and cut to
:data:`MAX_SIG` characters, so "Received SIGTERM at step 1200" and "... step
87" count as one signature. The fold keeps per signature how many notes had
it and the timestamp of the latest, at most :data:`MAX_SIGS` per run: a new
signature past that evicts the kept one with the fewest notes, the least
recently seen of those — so the most frequent ones stay and the newest
always enters. (Like any cap applied while folding, which one is evicted
follows the order entries are folded in.)

The index keeps the result, ``{sig: {"count", "last_at"}}`` oldest first, in
its ``note_sigs`` side table (``IndexSnapshot.notes_of``), never on lean
rows; ``notes ~ "sigterm"`` matches it (:mod:`vmn_exp.core.query_extra`).

Pure: no storage, no clock.
"""
import json

from vmn_exp.core.status import parse_iso
from vmn_exp.core.text_mask import mask

MAX_SIGS = 8
MAX_SIG = 56  # characters of a signature as JSON stores it (escapes included)


def _cut(sig):
    sig = sig[:MAX_SIG]
    while len(json.dumps(sig)) > MAX_SIG + 2:
        sig = sig[:-1]
    return sig.rstrip()


def note_signature(text):
    """The signature of a note *text*, or None for a blank or non-str one."""
    if not isinstance(text, str):
        return None
    return _cut(mask(text)) or None


def apply_note(fold, entry, key):
    """Fold one ``note`` entry (*key*: its fold key) into *fold*'s
    ``note_sigs``: ``{sig: [count, last_at, *last key]}``."""
    sig = note_signature(entry.get("text"))
    if sig is None:
        return
    sigs = fold.setdefault("note_sigs", {})
    held = sigs.get(sig)
    if held is None:
        if len(sigs) >= MAX_SIGS:
            del sigs[min(sigs, key=lambda s: (sigs[s][0], tuple(sigs[s][2:])))]
        sigs[sig] = [1, entry.get("timestamp"), *key]
        return
    held[0] += 1
    if key >= tuple(held[2:]):
        held[1:] = [entry.get("timestamp"), *key]


def fold_note_sigs(fold):
    """``{sig: {"count", "last_at"}}`` of *fold*, the latest seen last, or None."""
    sigs = fold.get("note_sigs")
    if not sigs:
        return None
    ordered = sorted(sigs.items(), key=lambda item: tuple(item[1][2:]))
    return {sig: {"count": held[0], "last_at": held[1]} for sig, held in ordered}


def note_texts(value):
    """The signatures of a :func:`fold_note_sigs` *value*, what ``notes``
    queries match, or None."""
    return list(value) if value else None


def last_note_sig(value):
    """The signature of *value* seen last (its latest ``last_at``, else the
    later one listed), or None."""
    if not value:
        return None
    items = list(value.items())
    at = max(range(len(items)), key=lambda i: (str(items[i][1].get("last_at") or ""), i))
    return items[at][0]


def note_minutes(value):
    """The epoch minutes each signature of *value* was last seen in, sorted
    (unparseable times left out)."""
    minutes = []
    for held in (value or {}).values():
        parsed = parse_iso(held.get("last_at"))
        if parsed is not None:
            minutes.append(int(parsed.timestamp() // 60))
    return sorted(minutes)
