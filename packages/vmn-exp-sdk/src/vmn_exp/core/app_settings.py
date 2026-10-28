"""An app's store settings (docs/plans/28-training-health-at-a-glance.md A0).

The reader-facing subset of conf's ``experiment:`` block, kept in the store
(:mod:`vmn_exp.core.app_settings_store`) so a store workspace, which has no
checkout, reads it too: ``metrics.<name|glob>.{goal,summary,hidden,primary,
step_metric}`` and ``ui.*`` (``group_aggregate`` and ``stale_after_min``
checked, other ``ui`` keys kept as they are). A checkout's conf beats them,
per metric name and per ``ui`` key; they beat what runs declare. Pure.
"""
import math

import yaml

from vmn_exp.core.metric_summary import GOALS, SUMMARIES

GROUP_AGGREGATES = ("mean", "best", "median", "min", "max")
_TOP_KEYS = ("metrics", "ui")
_METRIC_FIELDS = {
    "goal": lambda v: v in GOALS,
    "summary": lambda v: v in SUMMARIES,
    "hidden": lambda v: isinstance(v, bool),
    "primary": lambda v: isinstance(v, bool),
    "step_metric": lambda v: isinstance(v, str) and bool(v),
}


def _positive_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


_UI_FIELDS = {
    "group_aggregate": lambda v: v in GROUP_AGGREGATES,
    "stale_after_min": _positive_number,
}


class SettingsError(ValueError):
    pass


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


def metrics_overlay(settings, conf_metrics):
    """The metrics schema: *conf_metrics* over *settings*' metrics, per name."""
    return {**(settings or {}).get("metrics", {}), **(conf_metrics or {})}


def ui_overlay(settings, conf_ui):
    """The ``ui`` block: *conf_ui* over *settings*' ``ui``, per key."""
    return {**(settings or {}).get("ui", {}), **(conf_ui or {})}
