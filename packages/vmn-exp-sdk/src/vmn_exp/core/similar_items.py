#!/usr/bin/env python3
"""A similar-runs result as the JSON item ``vmn-exp similar --json``, the SDK
reader and the submission hint read::

    {"app", "verstr", "name", "score", "reasons", "signals", "group_size",
     "author", "timestamp", "status", "goal": {"metric", "goal", "value"} | None,
     "note", "intent": {"text", "keywords"?, "generator"?, "truncated"?} | None,
     "features"}

``intent.text`` is the run's intent cut to :data:`INTENT_EXCERPT_BYTES`;
``note`` the record's note, else its create entry's. Every string of an item
is UTF-8 (:func:`utf8_safe`), whatever a hand-written log holds.
"""
import copy

from vmn_exp.core.intent import cap_utf8

INTENT_EXCERPT_BYTES = 2048


def utf8_safe(value):
    """*value* with ``?`` for each lone surrogate of its strings (dict keys
    too): no UTF-8 encoder, JSON or stdout, fails on it. Dicts and lists are
    copied; tuples become lists."""
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return value.encode("utf-8", "replace").decode("utf-8")
        return value
    if isinstance(value, dict):
        return {utf8_safe(k): utf8_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [utf8_safe(v) for v in value]
    return copy.deepcopy(value)


def item_payload(item, rows):
    """A :func:`~vmn_exp.core.similar.similar_runs_multi` item as its JSON
    item, its facts read from *rows* (:mod:`vmn_exp.core.similar_rows`);
    copies only."""
    verstr, row = item["verstr"], item["row"]
    features, intent, _, _, create_note = rows.facts(row)
    return utf8_safe({
        "app": item["app"],
        "verstr": verstr,
        "name": row.get("name"),
        "score": item["score"],
        "reasons": item["reasons"],
        "signals": item["signals"],
        "group_size": item["group_size"],
        "author": row.get("author"),
        "timestamp": row.get("timestamp"),
        "status": rows.status_of(verstr),
        "goal": item.get("goal"),
        "note": row.get("note") or create_note,
        "intent": intent_excerpt(intent),
        "features": features,
    })


def intent_excerpt(intent):
    """*intent*'s text cut to :data:`INTENT_EXCERPT_BYTES` of UTF-8 (on a
    character boundary; ``truncated`` when cut, or cut when written), with
    its string ``keywords`` and its ``generator``; None without one. A lone
    surrogate (only a hand-written log holds one) is no UTF-8: it reads ``?``."""
    if not intent:
        return None
    found = {"keywords": _string_keywords(intent.get("keywords")),
             "generator": utf8_safe(intent.get("generator"))}
    excerpt = {key: value for key, value in found.items() if value}
    excerpt["text"], cut = cap_utf8(utf8_safe(str(intent.get("text") or "")),
                                    INTENT_EXCERPT_BYTES)
    if cut or intent.get("truncated"):
        excerpt["truncated"] = True
    return excerpt


def _string_keywords(keywords):
    """The strings of a folded intent's *keywords*: the fold checks only its
    text, and readers (the web UI) take each keyword for a string."""
    if not isinstance(keywords, (list, tuple)):
        return []
    return [utf8_safe(k) for k in keywords if isinstance(k, str)]
