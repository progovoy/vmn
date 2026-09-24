#!/usr/bin/env python3
"""Read a growing JSONL log from a byte offset, complete lines only.

Writers append whole lines, so everything up to the last newline is final.
What follows it is nothing, a line still being written, or a complete JSON
object whose newline has not landed yet. The experiment index and the ui's
parsed-log cache both read logs this way.

*files* is duck-typed: anything with ``read_file_from(app, verstr, name,
offset)`` returning bytes or None.
"""
from version_stamp.core.experiment_logfiles import parse_json_line


class UnterminatedEntry(Exception):
    """The data ends in a complete JSON line with no newline yet."""


def read_complete_lines(
    files, app_name, verstr, name, offset, take_unterminated=True, errors="replace"
):
    """``(entries, bytes consumed)`` of *name*'s lines past *offset*, or None
    when the file is missing.

    An unterminated last line that is valid JSON is taken when
    *take_unterminated*, else :class:`UnterminatedEntry` is raised; any other
    unterminated tail is left for the next read. Complete lines are decoded
    with the *errors* handler.
    """
    data = files.read_file_from(app_name, verstr, name, offset)
    if data is None:
        return None
    cut = data.rfind(b"\n") + 1
    tail = data[cut:]
    last = parse_json_line(tail.decode("utf-8", "replace"))
    if last is not None and not take_unterminated:
        raise UnterminatedEntry()
    lines = data[:cut].decode("utf-8", errors).splitlines()
    entries = [e for e in map(parse_json_line, lines) if e is not None]
    if last is None:
        return entries, len(data) if not tail.strip() else cut
    entries.append(last)
    return entries, len(data)
