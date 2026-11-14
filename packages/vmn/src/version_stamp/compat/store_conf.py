"""Conf ``experiment.storage`` -> top-level ``store`` (plan 37).

The store resolver (``version_stamp.store.config``) reads both, ``store``
first, so loading only flags the legacy section; ``vmn stamp`` moves it in
the conf file text through ``rewrite_deprecated_conf_keys``, keeping comments
and key order. An ``experiment`` left empty is dropped (as an emptied
``version_backends`` is). A set ``store`` leaves the legacy section alone.

Safe to remove when: all conf.yml files have gone through a stamp that
rewrites them, and vmn-exp reads ``store``.
"""
from version_stamp.compat.conf_rewrite import (
    _BLANK_OR_COMMENT,
    _block_end,
    _conf_keys,
    _find_direct_key,
    _flow_head,
    _flow_value,
    _is_content,
    _without_flow_key,
)

_EMPTY_VALUES = ("", "{}", "null", "~")


def has_legacy_storage(conf):
    """Whether *conf* (the dict under ``conf:``) has an ``experiment.storage``
    that ``vmn stamp`` moves to ``store``."""
    experiment = conf.get("experiment")
    return (
        isinstance(experiment, dict)
        and bool(experiment.get("storage"))
        and not conf.get("store")
    )


def move_storage_lines(lines):
    """The conf file ``lines`` with ``experiment.storage`` moved to ``store``;
    ``lines`` unchanged when there is nothing to move."""
    keys = {name: (i, ind, rest) for i, ind, name, rest in _conf_keys(lines)}
    if "experiment" not in keys:
        return lines
    if "store" in keys:
        if not _is_empty(lines, *keys["store"]):
            return lines
        without_store = _drop_block(lines, keys["store"][0])
        moved = move_storage_lines(without_store)
        return lines if moved is without_store else moved
    i, ind, rest = keys["experiment"]
    if _BLANK_OR_COMMENT.match(rest):
        return _move_from_block(lines, i, ind)
    return _move_from_flow(lines, i, ind, rest)


def _is_empty(lines, i, ind, rest):
    has_children = _block_end(lines, i) > i + 1
    return not has_children and rest.split("#", 1)[0].strip() in _EMPTY_VALUES


def _drop_block(lines, i):
    return lines[:i] + lines[_block_end(lines, i) :]


def _dedent(line, width):
    spaces = len(line) - len(line.lstrip(" "))
    return line[min(spaces, width) :]


def _move_from_block(lines, i, ind):
    found = _find_direct_key(lines, i, "storage")
    if found is None:
        return lines
    j, storage_ind, _, storage_rest = found
    storage_end, experiment_end = _block_end(lines, j), _block_end(lines, i)
    store = [f"{' ' * ind}store:{storage_rest}\n"] + [
        _dedent(line, storage_ind - ind) for line in lines[j + 1 : storage_end]
    ]
    remaining = lines[i + 1 : j] + lines[storage_end:experiment_end]
    if any(_is_content(line) for line in remaining):
        head = [lines[i]]
    else:  # only comments are left: they move out with the dropped experiment
        head = []
        remaining = [_dedent(line, storage_ind - ind) for line in remaining]
    return lines[:i] + head + remaining + store + lines[experiment_end:]


def _move_from_flow(lines, i, ind, rest):
    removed, entries, tail = _without_flow_key(rest, "storage")
    if removed is None:
        return lines
    head = _flow_head(ind, "experiment", entries, tail, empty=None)
    store = [f"{' ' * ind}store: {_flow_value(removed).strip()}\n"]
    return lines[:i] + head + store + lines[i + 1 :]
