#!/usr/bin/env python3
"""Rows and machine-readable payloads for ``vmn-exp list`` / ``vmn-exp show``.

A list row is exactly what ``vmn_exp.sdk.reader.list_runs`` returns: the
index row, its derived status fields and its place in the run tree. ``show
--json`` adds the run's metadata, patch sizes, features and (the tail of) its
log, and with ``--patch`` the patch text itself (capped).
Non-finite metrics are written as ``null`` so the output is strict JSON.
"""
import argparse
import json
import math
import sys
import tarfile
import zlib

from version_stamp.api import _list_tarball_members
from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.core.app_settings_store import app_metrics_schema
from vmn_exp.core.code_store import CODE_MISSING
from vmn_exp.core.fold import fold_features, fold_log, fold_row
from vmn_exp.core.intent import cap_utf8
from vmn_exp.core.media import media_counts
from vmn_exp.core.provenance import no_code_reason
from vmn_exp.core.record_format import record_format_version
from vmn_exp.core.run_error import error_summary
from vmn_exp.core.status import status_fields

PATCH_TYPES = ("working_tree", "local_commits")
# ``show --patch`` prints at most this much patch text unless ``--max-bytes`` says otherwise.
PATCH_MAX_BYTES = 200000
# ``show --patch``'s reason for a run whose code is untracked files only.
UNTRACKED_ONLY = "untracked_only"
# Log entries that record facts about the run rather than events in it.
FACT_ENTRY_TYPES = frozenset({"features"})


def plural(n, word):
    """``1 run``, ``2 runs``."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def metrics_schema(vcs, storage, app_name):
    """``experiment.metrics`` from the app's conf.yml over its store settings
    (:mod:`vmn_exp.core.app_settings`): sort direction and summary policies
    (see :mod:`vmn_exp.core.metric_summary`)."""
    return app_metrics_schema(storage, app_name, experiment_conf(vcs).get("metrics"))


def patch_lines(patches):
    """``{patch type: line count}`` for the patches present."""
    return {p: patches[p].count("\n") for p in PATCH_TYPES if (patches or {}).get(p)}


def _patch_sources(patches):
    """``(label prefix, patches)``: the run's own, then each dep's (``deps/<dep>/``)."""
    deps = patches.get("deps") or {}
    return [("", patches)] + [(f"deps/{name}/", deps[name]) for name in sorted(deps)]


def _text_patches(patches):
    """``(label, text)`` per text patch. The untracked tarball is binary, never shown."""
    return [
        (prefix + ptype, source[ptype])
        for prefix, source in _patch_sources(patches)
        for ptype in PATCH_TYPES
        if source.get(ptype)
    ]


def positive_max_bytes(text):
    """argparse type of ``--max-bytes``: an int of at least 1."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive number of bytes, not {value}")
    return value


def positive_int(text):
    """argparse type of a count of at least 1."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, not {value}")
    return value


def _untracked_names(patches):
    """The paths in the untracked tarballs, dep paths under ``deps/<dep>/``;
    None when a tarball cannot be read (corrupt, cut short)."""
    names = []
    for prefix, source in _patch_sources(patches):
        if source.get("untracked_files"):
            try:
                members = _list_tarball_members(source["untracked_files"])
            except (tarfile.TarError, EOFError, OSError, zlib.error):
                return None
            names += [prefix + name for name in members]
    return names


def _section(label, text):
    return f"=== {label} ===\n{text}" + ("" if text.endswith("\n") else "\n")


def _no_text_payload(metadata, patches):
    if metadata.get(CODE_MISSING):
        return {"text": None, "reason": CODE_MISSING}
    untracked = _untracked_names(patches)
    if untracked is None:
        return {"text": None, "reason": UNTRACKED_ONLY}
    if untracked:
        return {"text": None, "reason": UNTRACKED_ONLY, "untracked_files": untracked}
    return {"text": None, "reason": "no_code"}


def patch_payload(metadata, patches, max_bytes=PATCH_MAX_BYTES):
    """``show --patch``'s ``{"text", "truncated"}``, capped at *max_bytes*.
    A run without a text patch gets
    ``{"text": None, "reason"}``: ``code_missing``, ``untracked_only`` (plus
    the ``untracked_files`` paths, unless a tarball cannot be read) or ``no_code``."""
    sections = _text_patches(patches or {})
    if not sections:
        return _no_text_payload(metadata or {}, patches or {})
    text = "".join(_section(*s) for s in sections)
    text, truncated = cap_utf8(text, max_bytes)
    return {"text": text, "truncated": truncated}


def _untracked_only_note(names):
    if not names:
        return "only untracked files were captured, in a tarball that cannot be read"
    shown = ", ".join(names[:3]) + (f", +{len(names) - 3} more" if len(names) > 3 else "")
    return (
        f"only untracked files were captured ({shown}), which are not printed; "
        "vmn-exp export or vmn-exp restore brings them back"
    )


def no_patch_note(verstr, metadata, untracked=None):
    """One line on why *verstr* has no patch to show; *untracked* are the
    paths of a run whose code is untracked files only ([] when its tarball
    cannot be read)."""
    reason = no_code_reason(metadata)
    if reason is None:
        if untracked is not None:
            reason = _untracked_only_note(untracked)
        elif metadata.get("from_snapshot"):
            reason = "recorded from an exported snapshot, whose patches are not on the record"
        else:
            reason = f"clean tree at {(metadata.get('base_commit') or '?')[:7]}"
    return f"{verstr} has no patch to show: {reason}"


def print_patch(verstr, metadata, patches, max_bytes=PATCH_MAX_BYTES):
    """``show --patch``'s text: the patches, or a one-line note on stderr."""
    payload = patch_payload(metadata, patches, max_bytes)
    if payload["text"] is None:
        untracked = (payload.get("untracked_files", [])
                     if payload["reason"] == UNTRACKED_ONLY else None)
        print(no_patch_note(verstr, metadata, untracked), file=sys.stderr)
        return
    print("\n" + payload["text"], end="")
    if payload["truncated"]:
        print(f"\n[patch truncated at {max_bytes} bytes; raise --max-bytes to see more]")


def event_log(log):
    """*log* without its fact entries (:data:`FACT_ENTRY_TYPES`): what
    ``show`` lists as the run's log."""
    return [e for e in log if e.get("type") not in FACT_ENTRY_TYPES]


def show_payload(
    idx, metadata, patches, log, run_state, tree, log_tail=None, observed_at=None,
    schema=None,
):
    """The ``show --json`` object; *log_tail* keeps only the newest entries.
    *schema* is the app's metrics schema."""
    fold = fold_log(log)
    run = fold_row(idx, metadata, fold, schema=schema)
    run.update(status_fields(run_state, observed_at=observed_at))
    run.update(tree)
    run["base_commit"] = metadata.get("base_commit")
    run["format_version"] = record_format_version(metadata)
    run["has_dep_patches"] = bool(metadata.get("has_dep_patches"))
    run["patches"] = patch_lines(patches)
    events = event_log(log)
    run["log"] = events[-log_tail:] if log_tail else events
    run["log_total"] = len(events)
    run["features"] = fold_features(fold)
    run["media_counts"] = media_counts(log)
    run["error"] = (run_state or {}).get("error")
    return run


def error_lines(error):
    """``show``'s error block: the ``Type: message`` line, then the traceback
    (else the output tail) indented; [] without an error."""
    summary = error_summary(error)
    if not summary:
        return []
    detail = error.get("traceback") or error.get("output_tail") or ""
    return [summary] + [f"  {line}" for line in detail.splitlines()]


def format_number(value):
    """A metric value for display: floats to 4 significant digits."""
    return f"{value:.4g}" if isinstance(value, float) else str(value)


def format_metric_lines(metrics, summary):
    """``name: value`` per metric, name-ordered; a metric whose last, min and
    max differ adds them: ``loss: 0.2 (last 0.9, min 0.2, max 1)``."""
    lines = []
    for name, value in sorted(metrics.items()):
        line = f"{name}: {format_number(value)}"
        parts = summary.get(name)
        if parts and len({format_number(v) for v in parts.values()}) > 1:
            line += " (" + ", ".join(
                f"{k} {format_number(parts[k])}" for k in ("last", "min", "max")
            ) + ")"
        lines.append(line)
    return lines


def _finite_or_none(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite_or_none(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_or_none(v) for v in value]
    return value


def dumps(payload):
    """Strict, stable JSON: sorted keys, NaN/inf as ``null``."""
    return json.dumps(
        _finite_or_none(payload), indent=2, sort_keys=True, allow_nan=False, default=str
    )
