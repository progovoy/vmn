#!/usr/bin/env python3
"""What a run's log states about the run beyond its numbers.

A ``features`` entry holds the facts captured at submission (who ran it,
which files and functions the change touched, its commit subjects), an
``intent`` entry the description a human or their agent wrote, and the first
``create`` entry may carry the notes file's ``hypothesis``.
:mod:`vmn_exp.core.fold` folds them — the highest ``features_version`` wins,
the latest of those first; the latest intent wins; the hypothesis is the first
create entry's, like its note — through the values here. None of them is
pre-created by ``new_fold``, and a malformed entry folds into nothing.

Pure: no storage, no clock.
"""

_BOOKKEEPING = ("type", "timestamp", "_writer")  # _writer: the merged log's tag
_AUTHOR_KEYS = ("git_user_email", "os_user", "writer")


def _value(entry):
    return {k: v for k, v in entry.items() if k not in _BOOKKEEPING}


def features_value(entry):
    """``(features_version, value)`` of a ``features`` entry — the entry
    without its type, timestamp or ``_writer`` — or None without an int
    version."""
    version = entry.get("features_version")
    if not isinstance(version, int) or isinstance(version, bool):
        return None
    return version, _value(entry)


def intent_value(entry):
    """The value of an ``intent`` entry, or None without a text. An empty
    text is kept: as the latest intent, it clears the run's."""
    return _value(entry) if isinstance(entry.get("text"), str) else None


def entry_hypothesis(entry):
    """A ``create`` entry's hypothesis text, or None."""
    text = entry.get("hypothesis")
    return text if isinstance(text, str) and text.strip() else None


def fold_features(fold):
    """The run's winning ``features`` value, or None. Shared with the fold."""
    wrapped = fold.get("features")  # (value, version, *key) — see _keep_latest
    return wrapped[0] if wrapped else None


def fold_intent(fold):
    """The run's latest ``intent`` value with a non-blank text, or None.
    Shared with the fold."""
    wrapped = fold.get("intent")
    value = wrapped[0] if wrapped else None
    return value if value and value["text"].strip() else None


def fold_hypothesis(fold):
    """The first ``create`` entry's hypothesis, or None."""
    return fold.get("hypothesis")


def author_display(author):
    """Who a features ``author`` names: its git email, else its OS user, else
    its writer — empty values count as missing — or None."""
    if not isinstance(author, dict):
        return None
    for key in _AUTHOR_KEYS:
        value = author.get(key)
        if isinstance(value, str) and value:
            return value
    return None
