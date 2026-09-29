"""A small random forest regressor that only reports feature importance.

Pure Python, no numpy: features arrive pre-binned (small int codes, at most a
few dozen per column), so a node's best split per candidate feature is found
from a histogram of its bins — the rows are sorted by bin in C, each bin's
target sum is a difference of prefix sums, and only the bins (not the rows)
are scanned in Python. Ordered columns split on a bin threshold; unordered
(categorical) ones order their bins by mean target first, which is the exact
best binary partition for squared error (Breiman).

Importance is the mean decrease in impurity: every split credits its feature
with the squared-error reduction it bought, summed over the forest and
normalised to 1. Each tree sees a random subset of the rows and each node a
random subset of the features; a fixed seed makes the result reproducible.
"""
import math
import random
from itertools import groupby

TREES = 50
DEPTH = 6
MIN_LEAF = 5
TREE_ROWS = 1000


def forest_importance(columns, y, unordered, seed=0, trees=TREES, depth=DEPTH):
    """Per-column importance (summing to 1, or all 0 when nothing splits).

    *columns* holds one list of bin codes per feature, aligned with *y*;
    *unordered* flags the columns whose bins have no order.
    """
    rnd = random.Random(seed)
    mean = sum(y) / len(y) if y else 0.0
    y = [value - mean for value in y]  # centred: smaller sums, less rounding
    gains = [0.0] * len(columns)
    tries = min(len(columns), max(2, math.ceil(math.sqrt(len(columns)))))
    rows = range(len(y))
    for _ in range(trees):
        sample = rnd.sample(rows, min(len(y), TREE_ROWS))
        _grow(sample, columns, y, unordered, tries, depth, rnd, gains)
    total = sum(gains)
    return [gain / total if total > 0 else 0.0 for gain in gains]


def _grow(idx, columns, y, unordered, tries, depth, rnd, gains):
    stack = [(idx, 0)]
    features = range(len(columns))
    while stack:
        node, level = stack.pop()
        if level >= depth or len(node) < 2 * MIN_LEAF:
            continue
        best = None
        for f in rnd.sample(features, tries):
            split = _best_split(node, columns[f], y, unordered[f])
            if split and (best is None or split[0] > best[0]):
                best = split + (f,)
        if best is None:
            continue
        gain, ordered, size, left_bins, f = best
        gains[f] += gain
        if left_bins is not None:  # unordered: bring the left bins to the front
            ordered = sorted(ordered, key=lambda i: columns[f][i] not in left_bins)
        stack.append((ordered[:size], level + 1))
        stack.append((ordered[size:], level + 1))


def _histogram(ordered, col, y):
    """``[(bin, count, sum)]`` of *ordered* (rows sorted by bin)."""
    hist = []
    for code, members in groupby(ordered, key=col.__getitem__):
        members = list(members)
        hist.append((code, len(members), sum(map(y.__getitem__, members))))
    return hist


def _best_split(node, col, y, unordered):
    """The best split on *col* as ``(gain, rows sorted by bin, left size, left
    bins)`` — left bins only for an unordered column — or None. Only the
    winning candidate of a node gets partitioned."""
    ordered = sorted(node, key=col.__getitem__)
    hist = _histogram(ordered, col, y)
    if len(hist) < 2:
        return None
    if unordered:
        hist.sort(key=lambda b: b[2] / b[1])
    n = len(node)
    total = sum(b[2] for b in hist)
    base = total * total / n
    best_gain, cut, size, n_left, s_left = 0.0, None, 0, 0, 0.0
    for at, (_, count, s) in enumerate(hist[:-1]):
        n_left += count
        s_left += s
        n_right = n - n_left
        if n_left < MIN_LEAF or n_right < MIN_LEAF:
            continue
        s_right = total - s_left
        gain = s_left * s_left / n_left + s_right * s_right / n_right - base
        if gain > best_gain:
            best_gain, cut, size = gain, at, n_left
    if cut is None:
        return None
    left_bins = {b[0] for b in hist[: cut + 1]} if unordered else None
    return best_gain, ordered, size, left_bins
