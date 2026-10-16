#!/usr/bin/env python3
"""The weight of each similar-runs signal: the bm25 weight of its FTS column.

Signals: ``code`` (base commit, version, version line), ``files`` and
``symbols`` (changed, or a clean tree), ``inputs`` (digests, dataset names),
``params`` (keys and values), ``entrypoint`` (script, subcommand, args),
``objective`` (optimised metric names), ``branch`` and ``text``. Conf
``experiment.similar.weights`` overrides the defaults; odd values (non-finite,
negative, of the wrong shape) are ignored, never raised on.
"""
import logging
import math
from collections.abc import Mapping

# Stdlib logging, not VMN_LOGGER: the SDK reader searches runs too.
_LOGGER = logging.getLogger(__name__)

SIGNALS = ("code", "files", "symbols", "inputs", "params", "entrypoint",
           "objective", "branch", "text")
DEFAULT_WEIGHTS = {"code": 2.0, "files": 2.0, "symbols": 3.0, "inputs": 2.0, "params": 1.5,
                   "entrypoint": 1.0, "objective": 1.0, "branch": 0.5, "text": 1.5}
# The FTS column of each signal.
COLUMN_OF = dict(zip(SIGNALS, ("code", "files", "symbols", "inputs", "params", "entry",
                               "objective", "branch", "text")))
SIGNAL_OF = {column: signal for signal, column in COLUMN_OF.items()}


def _weight(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:  # an int no float holds
        return None
    return value if math.isfinite(value) and value >= 0 else None


def resolve_weights(overrides=None, intent=False):
    """:data:`DEFAULT_WEIGHTS` with the valid *overrides* (conf
    ``experiment.similar.weights``: known signals, numbers >= 0) merged over.
    With an *intent* on the target the default ``text`` weight becomes
    ``code + inputs``; an explicit ``text`` override still wins. Overrides
    that are no mapping are ignored."""
    weights = dict(DEFAULT_WEIGHTS)
    if overrides is not None and not isinstance(overrides, Mapping):
        _LOGGER.debug("Ignoring experiment.similar.weights, not a mapping: %r", overrides)
        overrides = None
    given = {k: _weight(v) for k, v in (overrides or {}).items() if k in weights}
    weights.update((k, v) for k, v in given.items() if v is not None)
    if intent and given.get("text") is None:
        weights["text"] = weights["code"] + weights["inputs"]
    return weights


# bm25 saturates a term's weighted frequency (tf * weight) at k1 = 1.2: a
# weight well below it scales a match's score about linearly, one above it
# hardly more than 1 does. Column weights are the signal weights scaled down
# into the linear range.
BM25_SCALE = 0.01


def column_weights(weights):
    """``{column: bm25 weight}`` of signal *weights*."""
    return {COLUMN_OF[signal]: weight * BM25_SCALE for signal, weight in weights.items()}
