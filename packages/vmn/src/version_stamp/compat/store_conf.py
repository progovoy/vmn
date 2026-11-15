"""Conf ``experiment.storage`` -> top-level ``store`` (plan 45).

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
    _direct_keys,
    _find_direct_key,
    _flow_head,
    _flow_key,
    _flow_value,
    _indent,
    _is_content,
    _split_flow,
    _without_flow_key,
)

# The ``experiment.storage`` keys that name the store; the others (vmn-exp's
# ``writer_id``, ``experiment_dir``) stay where they are.
STORE_KEYS = ("uri", "bucket", "prefix", "endpoint_url")
_EMPTY_VALUES = ("", "{}", "null", "~")


def has_legacy_storage(conf):
    """Whether *conf* (the dict under ``conf:``) has an ``experiment.storage``
    store that ``vmn stamp`` moves to ``store``."""
    experiment = conf.get("experiment")
    storage = experiment.get("storage") if isinstance(experiment, dict) else None
    return (
        isinstance(storage, dict)
        and any(storage.get(key) for key in STORE_KEYS)
        and not conf.get("store")
    )


def move_storage_lines(lines):
    """The conf file ``lines`` with the ``experiment.storage`` store keys moved
    to ``store``; ``lines`` unchanged when there is nothing to move."""
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
    return line[min(_indent(line), width) :]


def _move_from_block(lines, i, ind):
    found = _find_direct_key(lines, i, "storage")
    if found is None:
        return lines
    j, storage_ind, _, storage_rest = found
    storage_end, experiment_end = _block_end(lines, j), _block_end(lines, i)
    if _BLANK_OR_COMMENT.match(storage_rest):
        split = _split_block_storage(lines, j, storage_end, ind, storage_rest)
    else:
        split = _split_flow_storage(ind, storage_ind, storage_rest)
    if split is None:
        return lines
    kept_storage, store = split
    remaining = lines[i + 1 : j] + kept_storage + lines[storage_end:experiment_end]
    if any(_is_content(line) for line in remaining):
        head = [lines[i]]
    else:  # only comments are left: they move out with the dropped experiment
        head = []
        remaining = [_dedent(line, storage_ind - ind) for line in remaining]
    return lines[:i] + head + remaining + store + lines[experiment_end:]


def _split_block_storage(lines, j, storage_end, ind, storage_rest):
    """(the storage lines that stay, the ``store`` lines at indent ``ind``) of
    the block storage at ``j``, or None without a store key."""
    children = _direct_keys(lines, j)
    moved = [k[0] for k in children if k[2] in STORE_KEYS]
    if not moved:
        return None
    width = _indent(lines[j]) - ind
    if len(moved) == len(children):
        head = f"{' ' * ind}store:{storage_rest}\n"
        return [], [head] + [_dedent(c, width) for c in lines[j + 1 : storage_end]]
    moved_lines = {n for k in moved for n in range(k, _block_end(lines, k))}
    kept = [line for n, line in enumerate(lines[j:storage_end], j) if n not in moved_lines]
    store = [_dedent(lines[n], width) for n in sorted(moved_lines)]
    return kept, [f"{' ' * ind}store:\n"] + store


def _split_flow_storage(ind, storage_ind, storage_rest):
    parsed = _split_flow(storage_rest)
    if parsed is None:
        return None
    entries, tail = parsed
    moved = [e for e in entries if _flow_key(e) in STORE_KEYS]
    if not moved:
        return None
    kept = [e for e in entries if e not in moved]
    kept_line = _flow_head(storage_ind, "storage", kept, tail, empty=None)
    store_tail = "" if kept else tail
    return kept_line, [f"{' ' * ind}store: {{{', '.join(moved)}}}{store_tail}\n"]


def _move_from_flow(lines, i, ind, rest):
    removed, entries, tail = _without_flow_key(rest, "storage")
    if removed is None:
        return lines
    value = _flow_value(removed).strip()
    parsed = _split_flow(value)
    if parsed is None or not all(_flow_key(e) in STORE_KEYS for e in parsed[0]):
        return lines
    head = _flow_head(ind, "experiment", entries, tail, empty=None)
    store = [f"{' ' * ind}store: {value}\n"]
    return lines[:i] + head + store + lines[i + 1 :]
