#!/usr/bin/env python3
"""How ``vmn-exp show`` prints a run's logged images, tables and histograms."""
from vmn_exp.core.media import media_counts


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def media_lines(log):
    """``["images: 3 (2 keys)", ...]`` for the kinds the run logged."""
    return [
        f"{kind}: {c['entries']} ({_plural(c['keys'], 'key')})"
        for kind, c in media_counts(log).items()
        if c["entries"]
    ]


def describe_media_entry(entry):
    """One log line for an ``image``/``table``/``histogram`` entry, else None."""
    kind = entry.get("type")
    head = f"{kind}: {entry.get('name', '?')} @ step {entry.get('step', '?')}"
    if kind == "image":
        return f"{head} ({entry.get('path', '?')})"
    if kind == "table":
        return f"{head} ({entry.get('rows', 0)} rows)"
    if kind == "histogram":
        return f"{head} ({len(entry.get('counts') or [])} bins)"
    return None
