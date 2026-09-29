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
it is thinned as it arrives (about ``2 * MAX_HISTOGRAM_STEPS`` held) and its
view keeps at most :data:`MAX_HISTOGRAM_STEPS` evenly spaced steps, the first
and the last always among them.
"""
import bisect

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


class _Steps:
    """One name's items by step, in step order; steps arriving in order append."""

    def __init__(self):
        self._keys, self._steps, self._items = [], [], {}

    def __contains__(self, step):
        return step in self._items

    def __len__(self):
        return len(self._steps)

    def put(self, step, item):
        if step not in self._items:
            key = _step_key(step)
            at = len(self._keys)
            if at and key < self._keys[-1]:
                at = bisect.bisect_right(self._keys, key)
            self._keys.insert(at, key)
            self._steps.insert(at, step)
        self._items[step] = item

    def keep(self, wanted):
        """Drop every step *wanted(step)* rejects."""
        kept = [i for i, s in enumerate(self._steps) if wanted(s)]
        self._keys = [self._keys[i] for i in kept]
        self._steps = [self._steps[i] for i in kept]
        self._items = {s: self._items[s] for s in self._steps}

    def items(self):
        return [self._items[s] for s in self._steps]


class _ThinnedSteps:
    """A histogram name's steps, thinned on arrival to at most ``2 * limit``.

    The n-th distinct step is kept while n is a multiple of the stride, which
    doubles (dropping every other kept step) whenever too many are held; the
    first step and the last are always served.
    """

    def __init__(self, limit):
        self._limit = limit
        self._stride = 1
        self._rank = {}  # every step seen -> its arrival rank (ints only: cheap)
        self._kept = _Steps()
        self._last = None  # (step, item) with the highest step

    def __len__(self):
        return len(self._rank)

    def put(self, step, item):
        if step not in self._rank:
            self._rank[step] = len(self._rank)
            if self._rank[step] % self._stride == 0:
                self._kept.put(step, item)
                self._thin()
        elif step in self._kept:
            self._kept.put(step, item)
        if self._last is None or _step_key(step) >= _step_key(self._last[0]):
            self._last = (step, item)

    def _thin(self):
        if len(self._kept) <= 2 * self._limit:
            return
        self._stride *= 2
        self._kept.keep(lambda s: self._rank[s] % self._stride == 0)

    def items(self):
        items = self._kept.items()
        step, last = self._last
        if step not in self._kept:
            items.append(last)
        return _spread(items, self._limit)


class MediaIndex:
    """Grows with the log; :meth:`view` is the JSON-able index.

    A view rebuilds only the names that gained entries since the previous one;
    the others' lists are shared with it (never mutated afterwards).
    """

    def __init__(self):
        self._by_kind = {kind: {} for kind in _SECTIONS}  # kind -> name -> steps
        self._entries = {kind: 0 for kind in _SECTIONS}
        self._views = {kind: {} for kind in _SECTIONS}  # kind -> name -> list
        self._changed = {kind: set() for kind in _SECTIONS}

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
            names = self._by_kind[kind]
            if name not in names:
                hist = kind == "histogram"
                names[name] = _ThinnedSteps(MAX_HISTOGRAM_STEPS) if hist else _Steps()
            names[name].put(entry.get("step"), _item(entry))
            self._changed[kind].add(name)
        return added

    def extend(self, entries):
        self.add(entries)
        return self

    def _section(self, kind):
        views = self._views[kind]
        for name in self._changed[kind]:
            views[name] = self._by_kind[kind][name].items()
        self._changed[kind].clear()
        return {name: views[name] for name in sorted(views)}

    def view(self):
        return {
            "media": self._section("image"),
            "tables": self._section("table"),
            "histograms": self._section("histogram"),
            "histograms_total": {
                n: len(steps) for n, steps in sorted(self._by_kind["histogram"].items())
            },
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
