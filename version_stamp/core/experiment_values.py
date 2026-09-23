#!/usr/bin/env python3
"""Shaping the values that reach an experiment log.

Every log entry passes :func:`sanitize_entry` on its way to storage, so the
readers downstream — the fold, the leaderboard sort, the query language, the
charts — can rely on ``metrics`` values being plain floats. Without it a
``np.float32`` or a 0-d torch tensor was serialized as the *string* ``"0.5"``
(``json.dumps(default=str)``), which then broke sorting and silently failed
every numeric query.

Duck-typed on purpose: numpy and torch scalars are unwrapped through their
``.item()``, so nothing here imports either.
"""
import logging

# Stdlib logging, not VMN_LOGGER: the SDK writes through here without the CLI
# having initialized vmn's logger.
_LOGGER = logging.getLogger(__name__)

_CONTAINERS = (list, tuple, dict, set)


def _unwrap_scalar(value):
    """A numpy/torch scalar as its Python value; anything else unchanged."""
    if isinstance(value, (str, bytes, bool, int, float)):
        return value
    item = getattr(value, "item", None)
    if item is None:
        return value
    try:
        return item()
    except Exception:  # a vector: .item() only unwraps single elements
        return value


def metric_number(value):
    """*value* as a float metric, or None when it is not a number.

    Booleans are not metrics. Non-finite floats are numbers: a diverged loss
    really is NaN, and hiding that would be worse than showing it.
    """
    value = _unwrap_scalar(value)
    if isinstance(value, bool) or isinstance(value, _CONTAINERS):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def coerce_metric_values(values):
    """The numeric subset of *values*, as floats; the rest is dropped."""
    kept, dropped = {}, []
    for key, value in (values or {}).items():
        number = metric_number(value)
        if number is not None:
            kept[key] = number
        elif isinstance(_unwrap_scalar(value), bool):
            _LOGGER.debug("Not recording boolean metric '%s'", key)
        else:
            dropped.append(key)
    if dropped:
        _LOGGER.warning(
            "Dropped non-numeric metric value(s): %s", ", ".join(sorted(dropped))
        )
    return kept


def json_safe_params(params):
    """*params* with numpy/torch scalars unwrapped; strings and bools verbatim."""
    return {key: _unwrap_scalar(value) for key, value in params.items()}


def sanitize_entry(entry):
    """The entry as it should be stored, or None when nothing is left to store."""
    kind = entry.get("type")
    if kind == "metrics" and "values" in entry:
        values = coerce_metric_values(entry["values"])
        return dict(entry, values=values) if values else None
    if kind in ("create", "params") and isinstance(entry.get("params"), dict):
        return dict(entry, params=json_safe_params(entry["params"]))
    return entry
