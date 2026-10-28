"""An app's store settings (docs/plans/28-training-health-at-a-glance.md A0).

The reader-facing subset of conf's ``experiment:`` block, kept in the store
(:mod:`vmn_exp.core.app_settings_store`) so a store workspace, which has no
checkout, reads it too: ``metrics.<name|glob>.{goal,summary,hidden,primary,
step_metric}`` and ``ui.*`` (``group_aggregate``, ``stale_after_min``,
``progress`` and ``attention`` checked, other ``ui`` keys kept as they are). A
checkout's conf beats them, per metric name and per ``ui`` key; they beat what runs declare. Pure.
"""
import re

import yaml

from vmn_exp.core.metric_summary import GOALS, SUMMARIES
from vmn_exp.core.query import QueryError, compile_query
from vmn_exp.core.values import is_finite_number

GROUP_AGGREGATES = ("mean", "best", "median", "min", "max")
_TOP_KEYS = ("metrics", "ui")
_METRIC_FIELDS = {
    "goal": lambda v: v in GOALS,
    "summary": lambda v: v in SUMMARIES,
    "hidden": lambda v: isinstance(v, bool),
    "primary": lambda v: isinstance(v, bool),
    "step_metric": lambda v: isinstance(v, str) and bool(v),
}


PROGRESS_KEYS = ("done", "total", "unit")


def _progress_mapping(value):
    """``{done?, total?, unit?}``, each a non-empty name (plan 28 P2)."""
    return isinstance(value, dict) and all(
        key in PROGRESS_KEYS and isinstance(name, str) and name for key, name in value.items())


_UI_FIELDS = {
    "group_aggregate": lambda v: v in GROUP_AGGREGATES,
    "stale_after_min": lambda v: is_finite_number(v) and v > 0,
    "progress": _progress_mapping,
}


class SettingsError(ValueError):
    pass


# ``ui.attention`` (plan 28 P1): at most this many queries, after the
# built-in parts, whose keys they may not take.
MAX_ATTENTION = 8
ATTENTION_LEVELS = ("warn", "error")
BUILTIN_PARTS = ("stuck", "failed", "running", "outlived")
_ATTENTION_KEY = re.compile(r"[A-Za-z0-9_-]+")
_ATTENTION_FIELDS = {
    "key": lambda v: isinstance(v, str) and bool(_ATTENTION_KEY.fullmatch(v)),
    "label": lambda v: isinstance(v, str) and bool(v.strip()),
    "query": lambda v: isinstance(v, str) and bool(v.strip()),
    "level": lambda v: v in ATTENTION_LEVELS,
}


def parse_settings(text):
    """The validated settings *text* holds (``{}`` when empty); SettingsError
    naming the first bad key otherwise."""
    try:
        settings = yaml.safe_load(text or "")
    except yaml.YAMLError as exc:
        raise SettingsError(f"not valid YAML: {exc}") from None
    if settings is None:
        return {}
    _check_mapping(settings, "settings")
    for key in settings:
        if key not in _TOP_KEYS:
            raise SettingsError(f"unknown key {key!r}: settings hold {' and '.join(_TOP_KEYS)}")
    _check_metrics(settings.get("metrics", {}))
    _check_ui(settings.get("ui", {}))
    return settings


def check_settings(text):
    """:func:`parse_settings` for a save: also SettingsError on an attention
    query that does not compile (read from a conf, it is reported on its part)."""
    settings = parse_settings(text)
    for i, entry in enumerate((settings.get("ui") or {}).get("attention") or []):
        try:
            compile_query(entry["query"])
        except QueryError as error:
            raise SettingsError(f"invalid ui.attention[{i}].query: {error}") from None
    return settings


def _check_mapping(value, where):
    if not isinstance(value, dict):
        raise SettingsError(f"{where} must be a mapping")


def _check_metrics(metrics):
    _check_mapping(metrics, "metrics")
    for name, fields in metrics.items():
        _check_mapping(fields, f"metrics.{name}")
        for field, value in fields.items():
            valid = _METRIC_FIELDS.get(field)
            if valid is None:
                raise SettingsError(f"unknown field metrics.{name}.{field}; "
                                    f"one of {', '.join(_METRIC_FIELDS)}")
            if not valid(value):
                raise SettingsError(f"invalid metrics.{name}.{field}: {value!r}")
    if sum(1 for fields in metrics.values() if fields.get("primary")) > 1:
        raise SettingsError("more than one metric has primary: true")


def _check_ui(ui):
    _check_mapping(ui, "ui")
    for field, valid in _UI_FIELDS.items():
        if field in ui and not valid(ui[field]):
            raise SettingsError(f"invalid ui.{field}: {ui[field]!r}")
    if "attention" in ui:
        _check_attention(ui["attention"])


def _check_attention(entries):
    if not isinstance(entries, list):
        raise SettingsError("ui.attention must be a list")
    if len(entries) > MAX_ATTENTION:
        raise SettingsError(f"ui.attention holds at most {MAX_ATTENTION} queries")
    keys = set()
    for i, entry in enumerate(entries):
        where = f"ui.attention[{i}]"
        _check_mapping(entry, where)
        for field in ("key", "query"):
            if field not in entry:
                raise SettingsError(f"{where} needs a {field}")
        for field, value in entry.items():
            valid = _ATTENTION_FIELDS.get(field)
            if valid is None:
                raise SettingsError(f"unknown field {where}.{field}; "
                                    f"one of {', '.join(_ATTENTION_FIELDS)}")
            if not valid(value):
                raise SettingsError(f"invalid {where}.{field}: {value!r}")
        _check_attention_key(entry["key"], keys, where)


def _check_attention_key(key, keys, where):
    if key in BUILTIN_PARTS:
        raise SettingsError(f"{where}.key {key!r} is a built-in part")
    if key in keys:
        raise SettingsError(f"{where}.key {key!r} is used twice")
    keys.add(key)


def attention_entries(ui):
    """*ui*'s ``attention`` queries as ``{key, label, query, level}`` (label
    defaults to the key, level to ``warn``); none when it holds an invalid one."""
    entries = (ui or {}).get("attention") or []
    try:
        _check_attention(entries)
    except SettingsError:
        return []
    return [{"key": e["key"], "label": e.get("label", e["key"]), "query": e["query"],
             "level": e.get("level", "warn")} for e in entries]


def metrics_overlay(settings, conf_metrics):
    """The metrics schema: *conf_metrics* over *settings*' metrics, per name."""
    return {**(settings or {}).get("metrics", {}), **(conf_metrics or {})}


def ui_overlay(settings, conf_ui):
    """The ``ui`` block: *conf_ui* over *settings*' ``ui``, per key."""
    return {**(settings or {}).get("ui", {}), **(conf_ui or {})}
