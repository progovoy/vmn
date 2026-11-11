"""ui job actions that run ``vmn-exp experiment``: restore, prune, create, add,
note, tags, the archived flag, rewinds and pushes.

Everything here ends up as argv for a ``vmn-exp`` subprocess, so every input is
checked strictly (one path component per verstr, printable bounded tag keys and
values) and every token is built by :mod:`vmn_exp.ui.job_argv`: the app and
other positionals first, then each option as one ``--flag=value`` token.
"""
import re

from version_stamp.api import valid_path_component
from vmn_exp.ui.job_argv import opt, positional

MAX_TAG_KEY_LEN = 64
MAX_TAG_VALUE_LEN = 256
MAX_TAGS_PER_CALL = 100
MAX_ARCHIVE_BATCH = 500
MAX_NOTE_BYTES = 16 * 1024
_DURATION = re.compile(r"^\d+[dwh]$")


def _valid_verstr(value):
    return (
        isinstance(value, str)
        and valid_path_component(value)
        and not value.startswith("-")
    )


def _valid_text(value, max_len):
    return (
        isinstance(value, str)
        and len(value) <= max_len
        and value.isprintable()
        and not value.startswith("-")
    )


def _valid_note(note):
    return isinstance(note, str) and len(note.encode("utf-8")) <= MAX_NOTE_BYTES


def _valid_metric_name(key):
    return (
        isinstance(key, str)
        and bool(key)
        and not key.startswith("-")
        and "=" not in key
        and not any(c.isspace() for c in key)
    )


def _valid_metric_value(value):
    return isinstance(value, (int, float, str)) and not isinstance(value, bool)


def _valid_tag_key(key):
    return (
        bool(key)
        and _valid_text(key, MAX_TAG_KEY_LEN)
        and "=" not in key
        and not any(c.isspace() for c in key)
    )


def _exp(action, app_name, *tokens):
    return ["vmn-exp", "experiment", action, positional(app_name), *tokens]


def _metric_args(metrics):
    """Validate a {name: value} mapping and render one ``--metrics=k=v`` per
    metric. Returns (args, error_message_or_None); ``([], None)`` for none."""
    metrics = {} if metrics is None else metrics
    if not isinstance(metrics, dict):
        return None, "metrics must be an object"
    for key, value in metrics.items():
        if not _valid_metric_name(key):
            return None, f"Invalid metric name '{key}'"
        if not _valid_metric_value(value):
            return None, f"Invalid value for metric '{key}'"
    return [opt("--metrics", f"{k}={v}") for k, v in metrics.items()], None


def _note_args(note):
    """``--note=<text>`` for a non-empty note; (args, error_or_None)."""
    if note is None or note == "":
        return [], None
    if not _valid_note(note):
        return None, f"note must be a string of at most {MAX_NOTE_BYTES} bytes"
    return [opt("--note", note)], None


def exp_restore_command(app_name, body):
    verstr = body.get("verstr")
    if not _valid_verstr(verstr):
        return None, "A valid verstr is required"
    return _exp("restore", app_name, opt("--version", verstr)), None


def exp_prune_command(app_name, body):
    keep, older_than = body.get("keep"), body.get("older_than")
    if keep is not None:
        if isinstance(keep, bool) or not isinstance(keep, int) or keep < 0:
            return None, "keep must be an integer >= 0"
        return _exp("prune", app_name, opt("--keep", str(keep))), None
    if older_than:
        if not isinstance(older_than, str) or not _DURATION.match(older_than):
            return None, "older_than must be a duration like 30d, 2w or 24h"
        return _exp("prune", app_name, opt("--older-than", older_than)), None
    return None, "prune needs keep or older_than"


def exp_create_command(app_name, body):
    note_args, err = _note_args(body.get("note"))
    metric_args, metric_err = _metric_args(body.get("metrics"))
    if err or metric_err:
        return None, err or metric_err
    return _exp("create", app_name, *note_args, *metric_args), None


def exp_add_command(app_name, body):
    if not _valid_verstr(body.get("verstr")):
        return None, "A valid verstr is required"
    note_args, err = _note_args(body.get("note"))
    metric_args, metric_err = _metric_args(body.get("metrics"))
    if err or metric_err:
        return None, err or metric_err
    if not note_args and not metric_args:
        return None, "exp_add needs metrics or a note"
    return _exp("add", app_name, opt("--version", body["verstr"]),
                *note_args, *metric_args), None


def exp_note_command(app_name, body):
    verstr, note = body.get("verstr"), body.get("note")
    if not _valid_verstr(verstr) or not _valid_note(note):
        return None, f"verstr and a note of at most {MAX_NOTE_BYTES} bytes are required"
    return _exp("add", app_name, opt("--version", verstr), opt("--note", note)), None


def _tag_args(to_set, to_remove):
    if not isinstance(to_set, dict) or not isinstance(to_remove, list):
        return None, "set must be an object and remove a list"
    if not to_set and not to_remove:
        return None, "exp_tag needs tags to set or remove"
    if len(to_set) + len(to_remove) > MAX_TAGS_PER_CALL:
        return None, f"At most {MAX_TAGS_PER_CALL} tags per call"
    bad = next((k for k in [*to_set, *to_remove] if not _valid_tag_key(k)), None)
    if bad is not None:
        return None, f"Invalid tag key {bad!r}"
    for key, value in to_set.items():
        if not _valid_text(value, MAX_TAG_VALUE_LEN):
            return None, f"Invalid value for tag {key!r}"
    pairs = [positional(f"{k}={v}") for k, v in to_set.items()]
    return pairs + [opt("--remove", key) for key in to_remove], None


def exp_tag_command(app_name, body):
    verstr = body.get("verstr")
    if not _valid_verstr(verstr):
        return None, "A valid verstr is required"
    args, err = _tag_args(body.get("set") or {}, body.get("remove") or [])
    if err:
        return None, err
    return _exp("tag", app_name, positional(verstr), *args), None


def exp_archive_command(verb, app_name, body):
    """``vmn-exp experiment archive|unarchive <app> <verstr...>``."""
    verstrs = body.get("verstrs")
    if not isinstance(verstrs, list) or not verstrs:
        return None, "verstrs must be a non-empty list"
    if len(verstrs) > MAX_ARCHIVE_BATCH:
        return None, f"At most {MAX_ARCHIVE_BATCH} runs per call"
    if not all(_valid_verstr(v) for v in verstrs):
        return None, "Invalid verstr in verstrs"
    return _exp(verb, app_name, *map(positional, verstrs)), None


def exp_rewind_command(app_name, body):
    """``vmn-exp experiment rewind <app> --version=<verstr> --step=N``."""
    verstr, step = body.get("verstr"), body.get("step")
    if not _valid_verstr(verstr):
        return None, "A valid verstr is required"
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        return None, "step must be an integer >= 0"
    return _exp("rewind", app_name, opt("--version", verstr), opt("--step", str(step))), None


def exp_push_command(app_name, body):
    """``vmn-exp experiment push <app> [--version=<verstr>...]`` (every local
    run without verstrs)."""
    verstrs = body.get("verstrs") or []
    if not isinstance(verstrs, list) or not all(_valid_verstr(v) for v in verstrs):
        return None, "verstrs must be a list of valid verstrs"
    return _exp("push", app_name, *(opt("--version", v) for v in verstrs)), None
