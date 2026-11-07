"""A run's duration as the CLI prints it (plan 32 F13): the final one, the
elapsed time of a running run, or the lower bound of one that ended without
a recorded end, marked with its status (``≥ 3h (stuck)``)."""
from vmn_exp.core.status import RUNNING

_LADDER = ((86400, "d"), (3600, "h"), (60, "m"))


def humanize_sec(seconds, units=_LADDER):
    """``3h``-style text: the largest whole unit of *units* (default the
    web's ladder), floored, else seconds."""
    for size, unit in units:
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"


def duration_text(fields):
    """The duration text of :func:`~vmn_exp.core.status.status_fields`, or None."""
    if fields["duration_sec"] is not None:
        running = " (running)" if fields["status"] == RUNNING else ""
        return f"{fields['duration_sec']}s{running}"
    if fields["duration_at_least_sec"] is not None:
        return f"≥ {humanize_sec(fields['duration_at_least_sec'])} ({fields['status']})"
    return None
