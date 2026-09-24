"""ui job actions that edit a run's metadata: tags and the archived flag.

Everything here ends up as argv for a ``vmn`` subprocess, so every input is
checked strictly: one path component per verstr, printable bounded tag keys
and values, and nothing that starts with ``-`` (it would parse as a flag).
"""
from version_stamp.core.utils import valid_path_component

MAX_TAG_KEY_LEN = 64
MAX_TAG_VALUE_LEN = 256
MAX_TAGS_PER_CALL = 100
MAX_ARCHIVE_BATCH = 500


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


def _valid_tag_key(key):
    return (
        bool(key)
        and _valid_text(key, MAX_TAG_KEY_LEN)
        and "=" not in key
        and not any(c.isspace() for c in key)
    )


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
    args = [f"{k}={v}" for k, v in to_set.items()]
    for key in to_remove:
        args += ["--remove", key]
    return args, None


def exp_tag_command(app_name, body):
    verstr = body.get("verstr")
    if not _valid_verstr(verstr):
        return None, "A valid verstr is required"
    args, err = _tag_args(body.get("set") or {}, body.get("remove") or [])
    if err:
        return None, err
    return ["vmn", "experiment", "tag", app_name, verstr] + args, None


def exp_archive_command(verb, app_name, body):
    """``vmn experiment archive|unarchive <app> <verstr...>``."""
    verstrs = body.get("verstrs")
    if not isinstance(verstrs, list) or not verstrs:
        return None, "verstrs must be a non-empty list"
    if len(verstrs) > MAX_ARCHIVE_BATCH:
        return None, f"At most {MAX_ARCHIVE_BATCH} runs per call"
    if not all(_valid_verstr(v) for v in verstrs):
        return None, "Invalid verstr in verstrs"
    return ["vmn", "experiment", verb, app_name] + verstrs, None
