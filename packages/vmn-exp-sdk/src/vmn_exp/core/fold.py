#!/usr/bin/env python3
"""The leaderboard fold: the one place that turns log entries into a row.

A fold keeps, per field, the value carried by the entry with the greatest key.
:func:`fold_log` keys a log by list position — the last entry wins, which is
what ``experiment_row`` has always meant. The experiment index keys entries by
``(timestamp, writer, position in writer)`` instead: that is the order the
merged log is in (each writer's in file
order, stably sorted by timestamp), so entries can arrive in any chunks, per
writer, and still fold to the same row — a log that grew by one line costs one
line, not a re-read of the whole log.

A fold is plain JSON-able data, so the experiment index can persist it as is.
Pure: no storage, no clock.
"""
import math

from vmn_exp.core.metric_summary import note_param, summarize, track_extrema
from vmn_exp.core.step_metric import DEFINE_METRIC, entry_definition
from vmn_exp.core.rewind import is_rewound, rewind_step


def entry_params(entry):
    """Params carried by a log entry.

    `create` records params up front, `run.log_params()` mid-run.
    """
    if entry.get("type") in ("create", "params"):
        return entry.get("params") or {}
    return {}


def _foldable_param(value):
    """A param as a metric value: a finite number (bools fold as 1.0/0.0) — else None.

    ``missing=nan`` (xgboost's default) is a setting, not a measurement;
    folding it in made every such run carry a NaN "metric".
    """
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def new_fold(rewinds=()):
    """The fold of an empty log — knowing *rewinds* up front (see
    :func:`needs_refold`)."""
    return {
        "params": {},
        "metrics": {},
        "tags": {},
        "extrema": {},  # {metric: value, then (min, max, n, *sums)}, see metric_summary
        "metric_defs": {},
        "last_metric": None,
        "create_note": None,
        "rewinds": [list(r) for r in rewinds],
        "stale": False,
    }


def needs_refold(fold):
    """Whether *fold* met a rewind it did not know when it started: entries it
    folded earlier may be ones that rewind hides, so fold the log again from
    ``new_fold(fold_rewinds(fold))``."""
    return bool(fold.get("stale"))


def fold_rewinds(fold):
    """The ``[step, *key]`` rewinds *fold* has seen."""
    return [list(r) for r in fold.get("rewinds", ())]


def _learn_rewind(fold, step, key):
    """Record a rewind marker; a first sight of it makes the fold stale."""
    marker = [step, *key]
    known = fold.setdefault("rewinds", [])
    if marker not in known:
        known.append(marker)
        fold["stale"] = True


def entry_tags(entry):
    """``(set, removed)`` tag changes carried by a log entry.

    A ``tags`` entry sets and removes; a ``create`` entry may seed tags from a
    notes file, as a mapping or a list of bare labels.
    """
    etype = entry.get("type")
    if etype == "tags":
        return entry.get("set") or {}, entry.get("remove") or []
    if etype == "create":
        seeded = entry.get("tags")
        if isinstance(seeded, dict):
            return {str(k): str(v) for k, v in seeded.items()}, []
        if isinstance(seeded, list):
            return {str(k): "" for k in seeded}, []
    return {}, []


def _sort_key(entry, writer, position):
    ts = entry.get("timestamp", "")
    return (ts if isinstance(ts, str) else "", writer, position)


def _keep_latest(values, name, value, key):
    """Keep ``(value, *key)`` as one flat tuple — cheaper, with ~30 fields per
    run, than a value/key pair of two nested containers (see :func:`_sort_key`
    for *key*'s shape); the comparison takes the key back off its tail.
    ``tuple()`` normalises the stored slice so JSON-round-tripped lists compare
    correctly against the tuple *key*.
    """
    current = values.get(name)
    if current is None or key >= tuple(current[1:]):
        values[name] = (value,) + key


def _apply_tags(fold, entry, key):
    tags = fold.setdefault("tags", {})
    changed, removed = entry_tags(entry)
    for name, value in changed.items():
        _keep_latest(tags, name, value, key)
    for name in removed:
        _keep_latest(tags, name, None, key)  # a tombstone: removal is a write too


def _apply_inputs(fold, entry, key):
    """Fold one ``input`` entry; latest-(ts, writer, pos)-wins, matching tags."""
    name = entry.get("name")
    if not name:
        return
    value = {
        "uri": entry.get("uri"),
        "digest": entry.get("digest"),
        "kind": entry.get("kind"),
    }
    _keep_latest(fold.setdefault("inputs", {}), name, value, key)


# Entries that record a stored file of the run: an artifact, or a logged
# image/table (whose entry carries the file's sha256 and size itself).
# An image/table entry is logged only once its file is stored.
OUTPUT_TYPES = ("artifact", "image", "table")


def _apply_outputs(fold, entry, key):
    """Fold one output entry: the latest upload of a path wins."""
    path = entry.get("path")
    if not path:
        return
    sha = entry.get("sha256")
    value = {"path": path, "digest": f"sha256:{sha}" if sha else None,
             "size": entry.get("size")}
    _keep_latest(fold.setdefault("outputs", {}), path, value, key)


def _apply_metric_values(fold, entry, key):
    metrics = fold["metrics"]
    for name, value in (entry.get("values") or {}).items():
        track_extrema(fold, name, value, key)
        _keep_latest(metrics, name, value, key)


def _apply_definition(fold, entry, key):
    """Fold a ``define_metric`` entry's fields, each latest-wins."""
    definition = entry_definition(entry)
    if definition is None:
        return
    name, fields = definition
    declared = fold.setdefault("metric_defs", {}).setdefault(name, {})
    for field, value in fields.items():
        _keep_latest(declared, field, value, key)


def _apply(fold, entry, key):
    target = rewind_step(entry)
    if target is not None:
        _learn_rewind(fold, target, key)
        return
    if is_rewound(fold.get("rewinds"), entry, key):
        return
    etype = entry.get("type")
    if etype in ("tags", "create"):
        _apply_tags(fold, entry, key)
    elif etype == "input":
        _apply_inputs(fold, entry, key)
    elif etype in OUTPUT_TYPES:
        _apply_outputs(fold, entry, key)
    elif etype == DEFINE_METRIC:
        _apply_definition(fold, entry, key)
    for name, value in entry_params(entry).items():
        _keep_latest(fold["params"], name, value, key)
        number = _foldable_param(value)
        if number is not None:
            note_param(fold, name, key)
            _keep_latest(fold["metrics"], name, number, key)
    if etype == "metrics":
        _apply_metric_values(fold, entry, key)
        if fold["last_metric"] is None or key >= tuple(fold["last_metric"][1]):
            fold["last_metric"] = (entry.get("timestamp"), key)
    elif etype == "create":
        if fold["create_note"] is None or key < tuple(fold["create_note"][1]):
            fold["create_note"] = (entry.get("note"), key)


def apply_entries(fold, writer, first_position, entries):
    """Fold *entries* — *writer*'s log from *first_position* on — into *fold*."""
    for offset, entry in enumerate(entries):
        if isinstance(entry, dict):
            _apply(fold, entry, _sort_key(entry, writer, first_position + offset))
    return fold


def fold_log(log, fold=None, start=0):
    """The fold of *log* taken as given: every value is the last one in list order.

    With *fold* — the fold of the *start* entries before *log* — the entries
    are folded into it, so a log that grew folds only its new entries.
    """
    fold = new_fold() if fold is None else fold
    stale = fold.get("stale", False)
    for position, entry in enumerate(log, start):
        target = rewind_step(entry) if isinstance(entry, dict) else None
        if target is not None:
            _learn_rewind(fold, target, (position,))
    # The rewinds of *log* itself are learnt before it is folded; only one
    # that hides entries folded by an earlier call makes the fold stale.
    fold["stale"] = stale or (start > 0 and fold.get("stale", False))
    for position, entry in enumerate(log, start):
        if isinstance(entry, dict):
            _apply(fold, entry, (position,))
    return fold


def fold_values(fold, field):
    """``{name: value}`` of a fold's ``params`` or ``metrics``."""
    # Each entry is (value, *provenance) — see _keep_latest; only the value matters here.
    return {name: wrapped[0] for name, wrapped in fold[field].items()}


def fold_definitions(fold):
    """``{name: {field: value}}`` of the run's folded ``define_metric`` fields
    — summary policies and step metrics alike."""
    return {
        name: {field: wrapped[0] for field, wrapped in fields.items()}
        for name, fields in (fold.get("metric_defs") or {}).items()
    }


def fold_metrics(fold, schema=None):
    """``(metrics, metric_summary)`` of a fold — see :func:`summarize`.

    *schema* is the app's metrics schema; the run's own definitions beat it.
    """
    return summarize(
        fold_values(fold, "metrics"),
        fold.get("extrema") or {},
        fold_definitions(fold) if fold.get("metric_defs") else {},
        schema,
        fold.get("firsts"),
    )


def fold_tags(fold):
    """``{name: value}`` of the tags a fold holds (removed ones left out)."""
    return {
        name: wrapped[0]  # (value, *provenance) — see _keep_latest.
        for name, wrapped in fold.get("tags", {}).items()
        if wrapped[0] is not None
    }


def fold_inputs_dict(fold):
    """``{name: {uri, digest, kind}}`` of the inputs a fold holds."""
    return {
        name: wrapped[0]  # (value, *provenance) — see _keep_latest.
        for name, wrapped in fold.get("inputs", {}).items()
    }


def fold_outputs_dict(fold):
    """``{path: {path, digest, size}}`` of the files a run produced (its
    artifacts, images and tables)."""
    return {path: wrapped[0] for path, wrapped in fold.get("outputs", {}).items()}


def fold_last_metric_at(fold):
    return fold["last_metric"][0] if fold["last_metric"] else None


def _fork_fields(meta):
    """``forked_from`` flat (a verstr) so the query language can compare it."""
    origin = meta.get("forked_from") or {}
    return {"forked_from": origin.get("verstr"), "forked_from_step": origin.get("step")}


def fold_row(idx, meta, fold, with_create_note=False, schema=None):
    """The leaderboard row for *meta* whose log folded into *fold*.

    *idx* is the 1-based storage index — what ``vmn-exp show <app> -v @N``
    resolves — and is assigned before any sort so it sticks to the row.
    ``params`` carries every param verbatim; ``metrics`` stays numeric-only (with
    the numeric params folded in), because sorting and charting depend on that.
    ``with_create_note`` adds the first ``create`` entry's note (what
    ``vmn-exp list`` shows for a run without a metadata note). Each metric's
    value is its summary policy's (see :mod:`vmn_exp.core.metric_summary`,
    *schema* being the app's metrics schema); ``metric_summary`` has the
    last/min/max of every metric logged more than once.
    """
    metrics, metric_summary = fold_metrics(fold, schema)
    row = {
        "idx": idx,
        "verstr": meta["verstr"],
        "code_verstr": meta.get("code_verstr", meta["verstr"]),
        "timestamp": meta.get("timestamp"),
        "note": meta.get("note"),
        "branch": meta.get("branch"),
        "base_version": meta.get("base_version"),
        "name": meta.get("name"),
        "archived": bool(meta.get("archived", False)),
        "tags": fold_tags(fold),
        "params": fold_values(fold, "params"),
        "metrics": metrics,
        "metric_summary": metric_summary,
        "parent": meta.get("parent"),
        "last_metric_at": fold_last_metric_at(fold),
        "inputs": fold_inputs_dict(fold),
        "outputs": fold_outputs_dict(fold),
        "env": meta.get("env"),
        "imported_from": meta.get("imported_from"),
        **_fork_fields(meta),
        "rerun_of": meta.get("rerun_of"),
    }
    if with_create_note:
        row["create_note"] = fold["create_note"][0] if fold["create_note"] else None
    return row
