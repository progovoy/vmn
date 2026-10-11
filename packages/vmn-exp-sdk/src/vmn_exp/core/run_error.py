#!/usr/bin/env python3
"""What a failed run records about its failure: the ``error`` of ``run_state.yml``.

``error`` is a small mapping — ``type`` (the exception class, module-qualified
unless a builtin), ``message`` (``str(exc)``), ``traceback`` (capped), and
``source``: ``exception`` when the SDK caught the exception itself, ``output``
when it was parsed out of a run's captured output (which also keeps an
``output_tail``), ``user`` when ``run.finish(error="...")`` gave a message.

Pure functions only: the SDK and ``vmn-exp run`` build the mapping, readers
fold it into one ``error_summary`` line for lists and queries.
"""
import re
import traceback as _traceback

MAX_TRACEBACK_BYTES = 32 * 1024
TRACEBACK_HEAD_BYTES = 4 * 1024
OUTPUT_TAIL_LINES = 50
MAX_OUTPUT_TAIL_BYTES = 8 * 1024
MAX_SUMMARY_CHARS = 200

SOURCE_EXCEPTION = "exception"
SOURCE_OUTPUT = "output"
SOURCE_USER = "user"

_TRACEBACK_HEADER = "Traceback (most recent call last):"
# The line a traceback ends with: ``pkg.Type: message`` or a bare ``Type``.
_EXCEPTION_LINE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)(?::\s?(?P<message>.*))?$")


def exception_type_name(exc):
    """``__qualname__`` of *exc*'s class, prefixed by its module unless builtin."""
    cls = type(exc)
    module = getattr(cls, "__module__", None)
    if module in (None, "builtins"):
        return cls.__qualname__
    return f"{module}.{cls.__qualname__}"


def _message(exc):
    try:
        return str(exc)
    except Exception:
        return "<unprintable exception>"


def _format_traceback(exc):
    try:
        lines = _traceback.format_exception(type(exc), exc, exc.__traceback__)
    except Exception:
        lines = _traceback.format_exception_only(type(exc), exc)
    return "".join(lines).rstrip("\n")


def cap_head_tail(text, limit=MAX_TRACEBACK_BYTES, head=TRACEBACK_HEAD_BYTES):
    """*text* within *limit* bytes: its first *head* bytes, an elision marker
    and as much of its end as fits."""
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return text
    marker_len = len(f"\n... {len(raw)} bytes elided ...\n".encode())
    tail = limit - head - marker_len
    elided = len(raw) - head - tail
    marker = f"\n... {elided} bytes elided ...\n"
    return (
        raw[:head].decode("utf-8", errors="ignore")
        + marker
        + raw[len(raw) - tail:].decode("utf-8", errors="ignore")
    )


def cap_tail(text, limit):
    """The end of *text* within *limit* bytes."""
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return text
    return raw[len(raw) - limit:].decode("utf-8", errors="ignore")


def error_from_exception(exc):
    """The ``error`` mapping of an exception the run itself caught."""
    return {
        "type": exception_type_name(exc),
        "message": _message(exc),
        "traceback": cap_head_tail(_format_traceback(exc)),
        "source": SOURCE_EXCEPTION,
    }


def error_from_message(text):
    """The ``error`` mapping of a failure the workload described in words."""
    return {"message": str(text), "source": SOURCE_USER}


def output_tail(text):
    """The last :data:`OUTPUT_TAIL_LINES` lines of *text*, byte-capped."""
    lines = text.rstrip().splitlines()[-OUTPUT_TAIL_LINES:]
    return cap_tail("\n".join(lines), MAX_OUTPUT_TAIL_BYTES)


def _last_traceback(lines):
    """``(type, message, traceback)`` of the last traceback in *lines*, or None."""
    starts = [i for i, line in enumerate(lines) if line.strip() == _TRACEBACK_HEADER]
    if not starts:
        return None
    start = starts[-1]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()),
        None,
    )
    match = _EXCEPTION_LINE.match(lines[end].rstrip()) if end is not None else None
    if match is None:
        return None
    message = [match.group("message") or ""]
    last = end
    for line in lines[end + 1:]:
        if not line.strip():
            break
        message.append(line)
        last += 1
    tb = "\n".join(lines[start:last + 1])
    return match.group("type"), "\n".join(message).rstrip(), cap_head_tail(tb)


def error_from_output(text, traceback_text=None):
    """The ``error`` mapping parsed from a run's captured output.

    The last Python traceback in *traceback_text* (the child's stderr, where
    no stdout line can interleave with it; *text* when None) gives ``type``/
    ``message``/``traceback`` (chained exceptions end with the one that
    escaped); without one only the ``output_tail`` of *text* is kept. None for
    empty output.
    """
    if not text or not text.strip():
        return None
    error = {"source": SOURCE_OUTPUT, "output_tail": output_tail(text)}
    found = _last_traceback((text if traceback_text is None else traceback_text).splitlines())
    if found is not None:
        error["type"], error["message"], error["traceback"] = found
    return error


def _first_line(text):
    return str(text).strip().splitlines()[0] if text and str(text).strip() else ""


def _last_line(text):
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def _truncated(text):
    if len(text) <= MAX_SUMMARY_CHARS:
        return text
    return text[:MAX_SUMMARY_CHARS - 1] + "…"


def error_summary(error):
    """One line for an ``error`` mapping — ``Type: message`` — or None."""
    if not isinstance(error, dict):
        return None
    kind = error.get("type")
    message = _first_line(error.get("message"))
    if kind:
        summary = f"{kind}: {message}" if message else str(kind)
    else:
        summary = message or _last_line(error.get("output_tail"))
    return _truncated(summary) if summary else None
