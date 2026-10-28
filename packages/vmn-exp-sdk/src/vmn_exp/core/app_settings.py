"""An app's store settings (docs/plans/28-training-health-at-a-glance.md A0).

The reader-facing subset of conf's ``experiment:`` block, kept in the store
(:mod:`vmn_exp.core.app_settings_store`) so a store workspace, which has no
checkout, reads it too: ``metrics.<name|glob>.{goal,summary,hidden,primary,
step_metric}`` and ``ui.*`` (``group_aggregate``, ``stale_after_min``,
``progress``, ``attention``, ``baseline`` and ``views`` checked, other ``ui``
keys kept as they are). A checkout's conf beats them, per metric name and per
``ui`` key; they beat what runs declare. Pure.
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
    if "baseline" in ui:
        _check_baseline(ui["baseline"])
    if "views" in ui:
        _check_views(ui["views"])


def _check_attention(entries):
    _check_entries(entries, "ui.attention", MAX_ATTENTION, "queries", _ATTENTION_FIELDS,
                   ("key", "query"))
    keys = set()
    for i, entry in enumerate(entries):
        _check_attention_key(entry["key"], keys, f"ui.attention[{i}]")


def _check_entries(entries, where, cap, noun, fields, required):
    """*entries* as a list of at most *cap* mappings holding the *required*
    fields and only valid *fields*."""
    if not isinstance(entries, list):
        raise SettingsError(f"{where} must be a list")
    if len(entries) > cap:
        raise SettingsError(f"{where} holds at most {cap} {noun}")
    for i, entry in enumerate(entries):
        at = f"{where}[{i}]"
        _check_mapping(entry, at)
        for field in required:
            if field not in entry:
                raise SettingsError(f"{at} needs a {field}")
        for field, value in entry.items():
            valid = fields.get(field)
            if valid is None:
                raise SettingsError(f"unknown field {at}.{field}; one of {', '.join(fields)}")
            if not valid(value):
                raise SettingsError(f"invalid {at}.{field}: {value!r}")


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


# ``ui.baseline`` (plan 28 N3): the fields an outer run's baseline shares
# with it (``match``) and the field its direct children pair by
# (``children_by``), each a ``params.<k>``/``tags.<k>``.
MAX_BASELINE_MATCH = 8
_BASELINE_KEYS = ("match", "children_by")
_FIELD_PREFIXES = ("params", "tags")


def check_field(value, where):
    """*value* when it is a ``params.<k>``/``tags.<k>``, else SettingsError."""
    prefix, dot, name = value.partition(".") if isinstance(value, str) else ("", "", "")
    if not (dot and name.strip() and prefix in _FIELD_PREFIXES):
        raise SettingsError(f"invalid {where}: {value!r} (params.<key> or tags.<key>)")
    return value


def _check_match(fields, where):
    if not isinstance(fields, list):
        raise SettingsError(f"{where} must be a list")
    if len(fields) > MAX_BASELINE_MATCH:
        raise SettingsError(f"{where} holds at most {MAX_BASELINE_MATCH} fields")
    for i, field in enumerate(fields):
        check_field(field, f"{where}[{i}]")
    if len(set(fields)) < len(fields):
        raise SettingsError(f"{where} names a field twice")


def _check_baseline(baseline):
    _check_mapping(baseline, "ui.baseline")
    for key in baseline:
        if key not in _BASELINE_KEYS:
            raise SettingsError(f"unknown field ui.baseline.{key}; one of {', '.join(_BASELINE_KEYS)}")
    _check_match(baseline.get("match", []), "ui.baseline.match")
    if baseline.get("children_by") is not None:
        check_field(baseline["children_by"], "ui.baseline.children_by")


def baseline_conf(ui):
    """*ui*'s ``baseline`` as ``{match: [fields], children_by: field|None}``;
    no rule when it is invalid."""
    baseline = (ui or {}).get("baseline") or {}
    try:
        _check_baseline(baseline)
    except SettingsError:
        baseline = {}
    return {"match": list(baseline.get("match", [])), "children_by": baseline.get("children_by")}


def baseline_fields(text):
    """A URL's comma-separated ``match=`` fields; SettingsError on a bad one."""
    fields = [f.strip() for f in text.split(",")] if text.strip() else []
    _check_match(fields, "match")
    return fields


# ``ui.views`` (plan 28 P4): team views, each the URL query string a saved
# view of the page carries; one name per page, at most one default per page.
MAX_VIEWS = 20
VIEW_PAGES = ("jobs", "runs", "job")
_VIEW_FIELDS = {
    "name": lambda v: isinstance(v, str) and bool(v.strip()),
    "page": lambda v: v in VIEW_PAGES,
    "search": lambda v: isinstance(v, str),
    "default": lambda v: isinstance(v, bool),
}


def _check_views(views):
    _check_entries(views, "ui.views", MAX_VIEWS, "views", _VIEW_FIELDS, ("name", "page", "search"))
    names, defaults = set(), set()
    for i, view in enumerate(views):
        where, page, name = f"ui.views[{i}]", view["page"], view["name"]
        if (page, name) in names:
            raise SettingsError(f"{where}.name {name!r} is used twice on page {page}")
        names.add((page, name))
        if view.get("default"):
            if page in defaults:
                raise SettingsError(f"{where}: page {page} has more than one default view")
            defaults.add(page)


def views_entries(ui):
    """*ui*'s ``views`` as ``{name, page, search, default}`` (``search``
    with its ``?``, ``default`` false unless set); none when one is invalid."""
    views = (ui or {}).get("views") or []
    try:
        _check_views(views)
    except SettingsError:
        return []
    return [{"name": v["name"], "page": v["page"], "search": _search(v["search"]),
             "default": v.get("default", False)} for v in views]


def _search(text):
    query = text.strip().lstrip("?")
    return f"?{query}" if query else ""


def metrics_overlay(settings, conf_metrics):
    """The metrics schema: *conf_metrics* over *settings*' metrics, per name."""
    return {**(settings or {}).get("metrics", {}), **(conf_metrics or {})}


def ui_overlay(settings, conf_ui):
    """The ``ui`` block: *conf_ui* over *settings*' ``ui``, per key."""
    return {**(settings or {}).get("ui", {}), **(conf_ui or {})}
