#!/usr/bin/env python3
"""One copy of what the index's rows repeat.

Every row decoded from the index file, or folded from a log, has its own
copy of each key (metric, param and tag names, the row's own fields) and of
each value — a pod's image, profile and node name in every run's tags, the
same environment summary in every run's ``env``. :data:`STRINGS` hands out
one shared object per distinct value instead, and :func:`compact_row` makes a
row out of them: what a server holding half a million runs keeps is the
distinct values once, not once per run.

The table is bounded: once it holds :data:`LIMIT` entries it starts over
(values already shared stay shared), so values seen once — a log URI per
run — never pile up. Rows are read-only: shared values must not be changed.
"""
import json

LIMIT = 1 << 18
_ROW_STRINGS = ("code_verstr", "branch", "base_version", "parent", "forked_from",
                "rerun_of", "author")
_STATE_STRINGS = ("state", "host", "runner", "cwd", "end_reason", "signal")


class Interned:
    """``table(value)``: the shared object equal to *value* (hashable)."""

    def __init__(self, limit=LIMIT):
        self._table = {}
        self._limit = limit

    def __call__(self, value):
        return self.shared(value, value)

    def shared(self, key, value):
        """The object kept under *key*, *value* when none was."""
        found = self._table.get(key)
        if found is None:
            if len(self._table) >= self._limit:
                self._table.clear()
            found = self._table.setdefault(key, value)
        return found

    def __len__(self):
        return len(self._table)


STRINGS = Interned()
_SHARED = Interned()  # canonical JSON -> the one dict decoded from it


def _str(value):
    return STRINGS(value) if type(value) is str else value


def keyed(values):
    """*values* (a dict) with its keys and str values shared."""
    return {STRINGS(k): _str(v) for k, v in values.items()}


def shared_dict(value):
    """The one dict equal to *value* (a JSON-able dict) every row shares."""
    if not value:
        return value
    try:
        text = json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return value
    return _SHARED.shared(text, value)


def compact_row(row):
    """*row* (a lean row) made of shared keys and values: its own keys, its
    tags', params' and metrics' keys and str values (a numeric param folded
    into its metrics: the param's float), its str fields that repeat
    (branch, parent, ...) and its ``env``."""
    out = {STRINGS(k): v for k, v in row.items()}
    for name in ("tags", "params", "metrics"):
        if isinstance(out.get(name), dict):
            out[name] = keyed(out[name])
    if isinstance(out.get("params"), dict) and isinstance(out.get("metrics"), dict):
        out["metrics"] = _params_shared(out["metrics"], out["params"])
    for name in _ROW_STRINGS:
        if name in out:
            out[name] = _str(out[name])
    if isinstance(out.get("env"), dict):
        out["env"] = shared_dict(out["env"])
    return out


def _params_shared(metrics, params):
    for name, value in metrics.items():
        param = params.get(name)
        if type(value) is float and type(param) is float and param == value:
            metrics[name] = param
    return metrics


def compact_state(state):
    """A run state (or None) with shared keys, ``command`` words and the str
    values runs repeat (``state``, ``host``, ...)."""
    if not isinstance(state, dict):
        return state
    out = {STRINGS(k): v for k, v in state.items()}
    for name in _STATE_STRINGS:
        if name in out:
            out[name] = _str(out[name])
    command = out.get("command")
    if isinstance(command, list):
        out["command"] = [_str(word) for word in command]
    return out
