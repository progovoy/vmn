#!/usr/bin/env python3
"""``vmn-exp create|run|add <app> --intent "<text>" | --intent-file <path|->``:
what the run is for, as the ``intent`` log entry (see :mod:`vmn_exp.core.intent`).

An intent file may start with YAML front matter (``keywords:``, ``generator:``);
``-`` reads it from stdin. ``add`` writes onto the resolved run — the latest
without ``-v``, like ``--note`` — and its latest intent wins. The input is read
and checked before anything is written — a cold start's baseline stamp
included — so a bad one creates nothing; it is read once per invocation.
"""
import sys

from version_stamp.api import VMN_LOGGER
from vmn_exp._base import now_iso
from vmn_exp.core.intent import build_intent_entry, parse_intent_file
from vmn_exp.core.writer import append_to_log

# Where read_intent keeps the entry it read on the parsed args.
_READ = "_intent_entry_read"


def add_intent_flags(parser):
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--intent", default=None, metavar="TEXT",
                       help="create/run/add: what the run is for, matched by similar-run "
                            "search (add: on the latest run unless -v)")
    group.add_argument("--intent-file", dest="intent_file", default=None,
                       metavar="PATH|-",
                       help="create/run/add: like --intent, read from a file ('-': stdin) "
                            "that may start with YAML front matter (keywords, generator)")


def read_intent(args):
    """``(entry, None)`` for the intent *args* give — entry None without the
    flags — or ``(None, 1)`` after logging why the input is unusable. A later
    call returns the first one's entry (stdin is read once)."""
    if hasattr(args, _READ):
        return getattr(args, _READ), None
    try:
        entry = _intent_entry(args)
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return None, 1
    setattr(args, _READ, entry)
    return entry, None


def append_intent(storage, app_name, verstr, entry):
    """Append *entry* (from :func:`read_intent`) to the run, stamped now."""
    append_to_log(storage, app_name, verstr, dict(entry, timestamp=now_iso()))


def _intent_entry(args):
    path = getattr(args, "intent_file", None)
    if path is not None:
        return build_intent_entry(*parse_intent_file(read_file_arg(path, "--intent-file")))
    text = getattr(args, "intent", None)
    return None if text is None else build_intent_entry(text)


def read_file_arg(path, flag):
    """The text of the file *path* that *flag* names (``-``: stdin);
    ValueError when it can't be read."""
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"Cannot read {flag} {path}: {exc}") from None
