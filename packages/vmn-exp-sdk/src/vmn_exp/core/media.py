#!/usr/bin/env python3
"""Indexes of a run's logged images, tables and histograms.

``run.log_image``/``log_table``/``log_histogram`` append small ``image`` /
``table`` / ``histogram`` log entries (the image and table bodies are
artifacts). The index groups them per name, one item per step (the latest
entry for a step wins), ordered by step::

    {"media": {name: [{"step", "path", "caption", "width", "height"}]},
     "tables": {name: [{"step", "path", "rows", "columns", ...}]},
     "histograms": {name: [{"step", "bins", "counts"}]},
     "histograms_total": {name: steps logged}}

A histogram key logged every step would make the index grow with the run, so
its view keeps at most :data:`MAX_HISTOGRAM_STEPS` evenly spaced steps, the
first and the last always among them.
"""
MAX_HISTOGRAM_STEPS = 100

_SECTIONS = {"image": "media", "table": "tables", "histogram": "histograms"}
_COUNT_NAMES = {"image": "images", "table": "tables", "histogram": "histograms"}


def _item(entry):
    return {k: v for k, v in entry.items() if k not in ("type", "name", "timestamp", "_writer")}


def _spread(items, limit):
    """At most *limit* of *items*, evenly spaced, keeping both ends."""
    if len(items) <= limit:
        return items
    last = len(items) - 1
    picks = sorted({round(i * last / (limit - 1)) for i in range(limit)})
    return [items[i] for i in picks]


class MediaIndex:
    """Grows with the log; :meth:`view` is the JSON-able index."""

    def __init__(self):
        self._by_kind = {kind: {} for kind in _SECTIONS}  # kind -> name -> step -> item
        self._entries = {kind: 0 for kind in _SECTIONS}

    def add(self, entries):
        """Index *entries*; returns how many were media entries."""
        added = 0
        for entry in entries:
            kind = entry.get("type")
            name = entry.get("name")
            if kind not in _SECTIONS or not isinstance(name, str):
                continue
            added += 1
            self._entries[kind] += 1
            self._by_kind[kind].setdefault(name, {})[entry.get("step")] = _item(entry)
        return added

    def extend(self, entries):
        self.add(entries)
        return self

    def _sorted(self, kind):
        return {
            name: [steps[s] for s in sorted(steps, key=_step_key)]
            for name, steps in sorted(self._by_kind[kind].items())
        }

    def view(self):
        histograms = self._sorted("histogram")
        return {
            "media": self._sorted("image"),
            "tables": self._sorted("table"),
            "histograms": {
                n: _spread(items, MAX_HISTOGRAM_STEPS) for n, items in histograms.items()
            },
            "histograms_total": {n: len(items) for n, items in histograms.items()},
        }

    def counts(self):
        return {
            _COUNT_NAMES[kind]: {"keys": len(names), "entries": self._entries[kind]}
            for kind, names in self._by_kind.items()
        }


def _step_key(step):
    return (0, step) if isinstance(step, (int, float)) else (1, 0)


def media_index(log):
    return MediaIndex().extend(log).view()


def media_counts(log):
    """``{"images"|"tables"|"histograms": {"keys", "entries"}}``."""
    return MediaIndex().extend(log).counts()
