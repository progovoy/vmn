#!/usr/bin/env python3
"""What the grouped leaderboard (plan 22) groups by, and what a group says.

A group field is a link between runs (``parent``, ``forked_from``,
``rerun_of``: the run pointed at heads the group; ``code_verstr``: the code
state) or a row field (``branch``, ``status``, ``tags.<k>``, ``params.<k>``).
:func:`key_of` gives a row's group key, a pure function of the row; a
group's counts and aggregates live in :mod:`~vmn_exp.ui.leaderboard_group_summary`.
"""
import json

from vmn_exp.core.app_settings import GROUP_AGGREGATES as AGGREGATES

PARENT = "parent"
RERUN_OF = "rerun_of"
TARGET_LINKS = (PARENT, "forked_from", RERUN_OF)
LINKS = TARGET_LINKS + ("code_verstr",)
FIELDS = ("branch", "status", "failure_sig")
DICT_FIELDS = ("tags", "params")
DEFAULT_AGGREGATE = "mean"
# The no-value group's key: no value's key equals it, since a value whose
# text starts with it is keyed with it doubled (:func:`escaped_key`).
NONE = "\u2205"
NONE_LABEL = "(none)"
# A run's status as a group's counts name it; a settled run (core/settle.py)
# counts by its ``settled``: a lost one failed, a never-started one in the
# total only.
COUNT_OF = {"running": "running", "created": "waiting", "succeeded": "done",
            "failed": "failed", "stuck": "stuck", "lost": "failed"}
COUNT_KEYS = ("total", "running", "waiting", "done", "failed", "stuck")
# ``sort=`` values that order groups by a count, and the counts each sums
# (the board's inner-run count columns: ``failed`` takes stuck runs too).
COUNT_SORTS = {"c:total": ("total",), "c:waiting": ("waiting",), "c:running": ("running",),
               "c:done": ("done",), "c:failed": ("failed", "stuck")}


class UnknownGroup(LookupError):
    """A ``group_key`` no group of the board has."""


def check_group(group):
    """*group* when it is a field the board groups by, else ValueError."""
    prefix, dot, name = (group or "").partition(".")
    if group in LINKS or group in FIELDS or (dot and name and prefix in DICT_FIELDS):
        return group
    choices = ", ".join(LINKS + FIELDS + tuple(f"{p}.<key>" for p in DICT_FIELDS))
    raise ValueError(f"group must be one of {choices}, not {group!r}")


def check_aggregate(agg):
    if agg not in AGGREGATES:
        raise ValueError(f"agg must be one of {', '.join(AGGREGATES)}, not {agg!r}")
    return agg


def conf_aggregate(experiment_conf):
    """The app conf's ``experiment.ui.group_aggregate`` when valid, else the mean."""
    ui = (experiment_conf or {}).get("ui") or {}
    agg = ui.get("group_aggregate") if isinstance(ui, dict) else None
    return agg if agg in AGGREGATES else DEFAULT_AGGREGATE


def _text(value):
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)


def _absent(value):
    return value is None or value == ""


def escaped_key(text):
    """The group key of a value spelled *text*."""
    return NONE + text if text.startswith(NONE) else text


def key_text(key):
    """The value a group *key* (not :data:`NONE`) stands for: a link's verstr."""
    return key[len(NONE):] if key.startswith(NONE) else key


def key_of(group):
    """``row -> group key`` for *group* (a checked field)."""
    if group in TARGET_LINKS:
        def link(row):
            target = row.get(group)
            return NONE if _absent(target) or target == row["verstr"] else escaped_key(target)
        return link
    if group in LINKS or group in FIELDS:
        return lambda row: NONE if _absent(row.get(group)) else escaped_key(_text(row[group]))
    prefix, _, name = group.partition(".")

    def entry(row):
        value = (row.get(prefix) or {}).get(name)
        return NONE if value is None else escaped_key(_text(value))

    return entry


def label(group, key, found):
    """What a group's header says; *found*: whether a link's target is indexed."""
    if key == NONE:
        return NONE_LABEL
    text = key_text(key)
    if group in TARGET_LINKS:
        return text if found else f"{text} (not found)"
    if group in LINKS:
        return text
    return f"{group} = {text}"


def target_payload(row):
    """A link group's header run."""
    return {"verstr": row["verstr"], "idx": row.get("idx"), "name": row.get("name"),
            "status": row.get("status"), "tree_status": row.get("tree_status"),
            "metrics": row.get("metrics") or {}}
