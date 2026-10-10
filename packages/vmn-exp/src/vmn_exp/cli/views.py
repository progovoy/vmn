#!/usr/bin/env python3
"""Rows and machine-readable payloads for ``vmn-exp list`` / ``vmn-exp show``.

A list row is exactly what ``vmn_exp.sdk.reader.list_runs`` returns: the
index row, its derived status fields and its place in the run tree. ``show
--json`` adds the run's metadata, patch sizes and (the tail of) its log, and
with ``--patch`` the patch text itself (capped).
Non-finite metrics are written as ``null`` so the output is strict JSON.
"""
import json
import math
import sys

from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.core.code_store import CODE_MISSING
from vmn_exp.core.log import experiment_row
from vmn_exp.core.media import media_counts
from vmn_exp.core.provenance import no_code_reason
from vmn_exp.core.record_format import record_format_version
from vmn_exp.core.status import status_fields

PATCH_TYPES = ("working_tree", "local_commits")
# ``show --patch`` prints at most this much patch text unless ``--max-bytes`` says otherwise.
PATCH_MAX_BYTES = 200000


def metrics_schema(vcs):
    """``experiment.metrics`` from the app's conf.yml, if any: sort direction
    and summary policies (see :mod:`vmn_exp.core.metric_summary`)."""
    return experiment_conf(vcs).get("metrics") or {}


def patch_lines(patches):
    """``{patch type: line count}`` for the patches present."""
    return {p: patches[p].count("\n") for p in PATCH_TYPES if (patches or {}).get(p)}


def _text_patches(patches):
    """``(label, text)`` per text patch: the run's own, then each dep's
    (``deps/<dep>/<type>``). The untracked tarball is binary, never shown."""
    deps = patches.get("deps") or {}
    sources = [("", patches)] + [(f"deps/{name}/", deps[name]) for name in sorted(deps)]
    return [
        (prefix + ptype, source[ptype])
        for prefix, source in sources
        for ptype in PATCH_TYPES
        if source.get(ptype)
    ]


def _section(label, text):
    return f"=== {label} ===\n{text}" + ("" if text.endswith("\n") else "\n")


def _cap_utf8(text, max_bytes):
    """``(text, truncated)``: *text* cut to *max_bytes* UTF-8 bytes, never
    mid-character."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text, False
    return raw[:max_bytes].decode("utf-8", errors="ignore"), True


def _patch_cap(max_bytes):
    return PATCH_MAX_BYTES if max_bytes is None else max_bytes


def patch_payload(metadata, patches, max_bytes=None):
    """``show --patch``'s ``{"text", "truncated"}``, capped at *max_bytes*
    (default :data:`PATCH_MAX_BYTES`); ``{"text": None, "reason": "no_code" |
    "code_missing"}`` for a run without a text patch."""
    sections = _text_patches(patches or {})
    if not sections:
        reason = CODE_MISSING if (metadata or {}).get(CODE_MISSING) else "no_code"
        return {"text": None, "reason": reason}
    text = "".join(_section(*s) for s in sections)
    text, truncated = _cap_utf8(text, _patch_cap(max_bytes))
    return {"text": text, "truncated": truncated}


def no_patch_note(verstr, metadata):
    """One line on why *verstr* has no patch to show."""
    reason = no_code_reason(metadata)
    if reason is None:
        reason = (
            "recorded from an exported snapshot, whose patches are not on the record"
            if metadata.get("from_snapshot")
            else f"clean tree at {(metadata.get('base_commit') or '?')[:7]}"
        )
    return f"{verstr} has no patch to show: {reason}"


def print_patch(verstr, metadata, patches, max_bytes=None):
    """``show --patch``'s text: the patches, or a one-line note on stderr."""
    cap = _patch_cap(max_bytes)
    payload = patch_payload(metadata, patches, cap)
    if payload["text"] is None:
        print(no_patch_note(verstr, metadata), file=sys.stderr)
        return
    print("\n" + payload["text"], end="")
    if payload["truncated"]:
        print(f"\n[patch truncated at {cap} bytes; raise --max-bytes to see more]")


def show_payload(
    idx, metadata, patches, log, run_state, tree, log_tail=None, observed_at=None,
    schema=None,
):
    """The ``show --json`` object; *log_tail* keeps only the newest entries.
    *schema* is the app's metrics schema."""
    run = experiment_row(idx, metadata, log, schema=schema)
    run.update(status_fields(run_state, observed_at=observed_at))
    run.update(tree)
    run["base_commit"] = metadata.get("base_commit")
    run["format_version"] = record_format_version(metadata)
    run["has_dep_patches"] = bool(metadata.get("has_dep_patches"))
    run["patches"] = patch_lines(patches)
    run["log"] = log[-log_tail:] if log_tail else log
    run["log_total"] = len(log)
    run["media_counts"] = media_counts(log)
    return run


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
