#!/usr/bin/env python3
"""What the grouped leaderboard (plan 22) groups by, and what a group says.

A group field is a link between runs (``parent``, ``forked_from``,
``rerun_of``: the run pointed at heads the group; ``code_verstr``: the code
state), a row field (``branch``, ``status``, ``tags.<k>``, ``params.<k>``)
or an ancestor's (``up.params.<k>``, ``up(tags.kind = "study").params.<k>``,
plan 28 N1, :mod:`vmn_exp.core.query_up`). :func:`key_of` gives a row's
group key, a function of the row (and, for an ``up`` field, of the snapshot
it is in); a group's counts and aggregates live in
:mod:`~vmn_exp.ui.leaderboard_group_summary`.
"""
import json

from vmn_exp.core.app_settings import GROUP_AGGREGATES as AGGREGATES
from vmn_exp.core.query import QueryError, parse_field
from vmn_exp.core.query_up import ancestor_fields

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


def is_dict_field(field):
    """Whether *field* is a ``tags.<k>``/``params.<k>``."""
    prefix, dot, name = (field or "").partition(".")
    return bool(dot and name and prefix in DICT_FIELDS)


def up_node(group):
    """The ``up`` field node *group* names, None for any other group;
    ValueError when it is no ``up`` field the query language reads."""
    if not (group or "").startswith(("up.", "up(")):
        return None
    try:
        return parse_field(group)
    except QueryError as error:
        raise ValueError(f"group {group!r}: {error}") from None


def check_group(group):
    """*group* when it is a field the board groups by, else ValueError."""
    if group in LINKS or group in FIELDS or is_dict_field(group):
        return group
    if up_node(group) is not None:
        return group
    choices = ", ".join(LINKS + FIELDS + tuple(f"{p}.<key>" for p in DICT_FIELDS))
    raise ValueError(f"group must be one of {choices}, up.<field>, not {group!r}")


def check_aggregate(agg):
    if agg not in AGGREGATES:
        raise ValueError(f"agg must be one of {', '.join(AGGREGATES)}, not {agg!r}")
    return agg


def conf_aggregate(ui):
    """The app's ``experiment.ui`` block's ``group_aggregate`` when valid, else the mean."""
    agg = ui.get("group_aggregate")
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


def value_of(group, snapshot=None):
    """``row -> value`` *group* (a checked field, not a link) reads; an
    ``up`` field reads the ancestors in *snapshot*."""
    node = up_node(group)
    if node is not None:
        value = ancestor_fields(snapshot).value
        return lambda row: value(row["verstr"], node)
    prefix, dot, name = group.partition(".")
    if dot and prefix in DICT_FIELDS:
        return lambda row: (row.get(prefix) or {}).get(name)
    return lambda row: row.get(group)


def key_of(group, snapshot=None):
    """``row -> group key`` for *group* (a checked field); an ``up`` field
    reads the ancestors in *snapshot*."""
    if group in TARGET_LINKS:
        def link(row):
            target = row.get(group)
            return NONE if _absent(target) or target == row["verstr"] else escaped_key(target)
        return link
    if group in LINKS or group in FIELDS:
        return lambda row: NONE if _absent(row.get(group)) else escaped_key(_text(row[group]))
    value_in = value_of(group, snapshot)

    def entry(row):
        value = value_in(row)
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
