#!/usr/bin/env python3
"""How alike two runs are: one similarity in [0, 1] per signal, a weighted
mean, and the reasons behind it.

Signals (see the plan's table): ``code`` (same base commit 1.0, same base
version 0.7, else decaying with the version distance), ``files`` and
``symbols`` (Jaccard; half weight for a branch's cumulative change,
``changed_source: commit``), ``inputs`` (same digest 1.0, same dataset name
0.6), ``params`` (key Jaccard x mean value closeness), ``entrypoint`` (same
script 0.7, plus the same subcommand or args 1.0), ``objective`` (Jaccard of
the optimised metric names), ``branch`` (equality) and ``text`` (BM25,
normalised by the caller — :mod:`vmn_exp.core.similar`).

A signal missing on either side is left out and the weights of the others
renormalised: it is unknown, not different. Reasons read candidate first
(``lr 3e-4 vs 1e-4`` = the candidate's lr vs the target's). Pure; odd
values (non-finite or extreme params, conf weights of the wrong shape) never
raise.
"""
import logging
import math
from collections.abc import Mapping

from vmn_exp.core.similar_profile import as_profile
from vmn_exp.core.values import metric_number

# Stdlib logging, not VMN_LOGGER: the SDK reader scores runs too.
_LOGGER = logging.getLogger(__name__)

SIGNALS = ("code", "files", "symbols", "inputs", "params", "entrypoint",
           "objective", "branch", "text")
DEFAULT_WEIGHTS = {"code": 2.0, "files": 2.0, "symbols": 3.0, "inputs": 2.0, "params": 1.5,
                   "entrypoint": 1.0, "objective": 1.0, "branch": 0.5, "text": 1.5}
REASONS = 3
LISTED = 3

SAME_VERSION, SAME_DATASET, SAME_SCRIPT = 0.7, 0.6, 0.7
# (low, high] closeness of base versions that first differ at major, minor,
# patch, hotfix; a version core equal but for a prerelease scores SAME_CORE.
_VERSION_BANDS = ((0.0, 0.15), (0.15, 0.35), (0.35, 0.55), (0.55, 0.65))
SAME_CORE = 0.65


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


def _listed(names):
    names = list(names)
    shown = ", ".join(names[:LISTED])
    return shown + (", …" if len(names) > LISTED else "")


def _counted(names, noun):
    return f"{len(names)} shared {noun}{'' if len(names) == 1 else 's'}: {_listed(names)}"


def _number(value):
    """A param as a finite float (numeric strings too), else None."""
    number = metric_number(value)
    return number if number is not None and math.isfinite(number) else None


def _same(a, b):
    """Equality of two JSON values where a bool never equals a number."""
    return isinstance(a, bool) == isinstance(b, bool) and a == b


def value_closeness(a, b):
    """1 for equal values; positive numbers ``1 - min(1, |log10(a/b)| / 2)``;
    0 when either is NaN or infinite (not comparable)."""
    x, y = metric_number(a), metric_number(b)
    if any(n is not None and not math.isfinite(n) for n in (x, y)):
        return 0.0
    if x is not None and y is not None:
        if x > 0 and y > 0:
            # A difference of logs: the ratio itself under- or overflows.
            return 1 - min(1.0, abs(math.log10(x) - math.log10(y)) / 2)
        return 1.0 if x == y else 0.0
    return 1.0 if _same(a, b) else 0.0


def _fmt(value):
    """A param value as a reason shows it: ``3e-4``, ``0.25``, ``adam``."""
    plain = isinstance(value, (int, float)) and not isinstance(value, bool)
    number = _number(value) if plain else None  # an int too big for a float is text
    if number is None:
        text = str(value)
        return text if len(text) <= 24 else text[:23] + "…"
    if number and (abs(number) < 1e-3 or abs(number) >= 1e6):
        mantissa, exponent = f"{number:.2e}".split("e")
        return f"{mantissa.rstrip('0').rstrip('.')}e{int(exponent)}"
    return f"{number:.4g}"


def _version(base):
    core = str(base or "").split("-", 1)[0].split("+", 1)[0].split(".")
    if not core or not all(part.isdigit() for part in core):
        return None
    return (tuple(int(part) for part in core) + (0, 0, 0, 0))[:4]


def version_closeness(a, b):
    """Closeness of two base versions below :data:`SAME_VERSION`: a nearer
    segment beats a farther one, and closer values within a segment beat
    farther ones; 0 when either does not parse."""
    va, vb = _version(a), _version(b)
    if va is None or vb is None:
        return 0.0
    for (low, high), x, y in zip(_VERSION_BANDS, va, vb):
        if x != y:
            return low + (high - low) * 0.5 ** (abs(x - y) - 1)
    return SAME_CORE


def _code(a, b):
    if not (a.commit or a.base) or not (b.commit or b.base):
        return None
    if a.commit and a.commit == b.commit:
        return 1.0, f"same base commit {b.commit}"
    if a.base and a.base == b.base:
        return SAME_VERSION, f"same base version {b.base}"
    near = version_closeness(a.base, b.base)
    return near, (f"base version {b.base} vs {a.base}" if near else None)


def _jaccard(a, b, describe):
    """Jaccard of two sets, with *describe(sorted shared items)* as the reason."""
    if not a or not b:
        return None
    shared = sorted(a & b)
    return len(shared) / len(a | b), (describe(shared) if shared else None)


def _short_symbol(symbol):
    path, sep, name = symbol.partition("::")
    return path.rsplit("/", 1)[-1] + sep + name


def _shared_files(files):
    return _counted(files, "file")


def _shared_functions(symbols):
    return _counted([_short_symbol(s) for s in symbols], "function")


def _same_metrics(names):
    return "same metrics: " + _listed(names)


def _inputs(a, b):
    if not a.inputs or not b.inputs:
        return None
    total, same, other = 0.0, [], []
    for mine in a.inputs:
        best, match = 0.0, None
        for theirs in b.inputs:
            if mine.digest and mine.digest == theirs.digest:
                best, match = 1.0, theirs
                break
            if not best and mine.dataset == theirs.dataset:
                best, match = SAME_DATASET, theirs
        total += best
        if best == 1.0:
            same.append(match)
        elif best:
            other.append((match, mine))
    if same:
        kind = "model" if same[0].kind == "model" else "dataset"
        reason = (f"same {kind} {same[0].name}" if len(same) == 1
                  else f"same inputs: {_listed(i.name for i in same)}")
    elif other:
        theirs, mine = other[0]
        reason = f"{'model' if theirs.kind == 'model' else 'dataset'} {theirs.name} vs {mine.name}"
    else:
        reason = None
    return total / max(len(a.inputs), len(b.inputs)), reason


def _params(a, b):
    if not a.params or not b.params:
        return None
    shared = sorted(set(a.params) & set(b.params))
    if not shared:
        return 0.0, None
    close = {k: value_closeness(b.params[k], a.params[k]) for k in shared}
    similarity = len(shared) / len(set(a.params) | set(b.params)) * sum(close.values()) / len(shared)
    differ = sorted((k for k in shared if not _same(a.params[k], b.params[k])),
                    key=lambda k: (close[k], k))
    if differ:
        reason = ", ".join(f"{k} {_fmt(b.params[k])} vs {_fmt(a.params[k])}" for k in differ[:2])
    else:
        reason = "same params: " + _listed(shared)
    return similarity, reason


def _subcommand(args):
    return args[0] if args and not args[0].startswith("-") else None


def _entrypoint(a, b):
    if not a.script or not b.script:
        return None
    if a.script != b.script:
        return 0.0, None
    sub = _subcommand(a.args)
    if a.args == b.args or (sub and sub == _subcommand(b.args)):
        return 1.0, " ".join(["same command", b.script] + ([sub] if sub else []))
    return SAME_SCRIPT, f"same script {b.script}"


def _branch(a, b):
    if not a.branch or not b.branch:
        return None
    return (1.0, f"same branch {b.branch}") if a.branch == b.branch else (0.0, None)


def signal_values(a, b):
    """``{signal: (similarity, reason or None)}`` of the structured signals
    both profiles carry."""
    found = {
        "code": _code(a, b),
        "files": _jaccard(a.files, b.files, _shared_files),
        "symbols": _jaccard(a.symbols, b.symbols, _shared_functions),
        "inputs": _inputs(a, b),
        "params": _params(a, b),
        "entrypoint": _entrypoint(a, b),
        "objective": _jaccard(a.objective, b.objective, _same_metrics),
        "branch": _branch(a, b),
    }
    return {name: value for name, value in found.items() if value is not None}


def score(target, candidate, weights=None, text_score=None, text_reason=None):
    """``(score, reasons, signals)`` of *candidate* against *target*.

    Both are profiles or run views (:func:`~vmn_exp.core.similar_profile.as_profile`);
    *weights* are overrides (:func:`resolve_weights`); *text_score* is the
    normalised text similarity, or None when either side has no text.
    ``signals`` is ``{signal: similarity}``; ``reasons`` the top
    :data:`REASONS` contributions' reasons.
    """
    a, b = as_profile(target), as_profile(candidate)
    w = resolve_weights(weights, intent=a.has_intent)
    if a.commit_changes or b.commit_changes:
        w["files"], w["symbols"] = w["files"] / 2, w["symbols"] / 2
    found = signal_values(a, b)
    if text_score is not None:
        found["text"] = (text_score, text_reason or ("similar text" if text_score else None))
    total = sum(w[name] for name in found)
    value = sum(w[name] * sim for name, (sim, _) in found.items()) / total if total else 0.0
    ranked = sorted(
        (name for name, (sim, reason) in found.items() if sim > 0 and w[name] and reason),
        key=lambda name: (-w[name] * found[name][0], SIGNALS.index(name)),
    )
    reasons = [found[name][1] for name in ranked[:REASONS]]
    return value, reasons, {name: sim for name, (sim, _) in found.items()}
