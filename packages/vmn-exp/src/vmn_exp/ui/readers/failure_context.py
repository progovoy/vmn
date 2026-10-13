#!/usr/bin/env python3
"""What a failed or stuck run's detail adds for its failure card (plan 20 K4).

``output_tail`` (the end of ``outputs/output.log``, one range read of at most
:data:`TAIL_BYTES`), ``last_step`` (how far it got, of how many when the
params say) and ``last_good`` (the latest earlier success of its command).
Runs in any other status carry none of them.
"""
from vmn_exp.core.output_log import OUTPUT_LOG_PATH

FAILURE_STATUSES = ("failed", "stuck")
TAIL_BYTES = 16 * 1024
TAIL_LINES = 40
_TOTAL_PARAMS = ("epochs", "max_steps")


def _shown(line):
    """What a terminal shows of *line*: the last ``\\r``-separated rewrite."""
    parts = [p for p in line.split("\r") if p]
    return parts[-1] if parts else ""


def output_tail(storage, app_name, verstr, artifacts):
    """``{"lines", "truncated"}`` of the output log's last lines, or None
    without one; *artifacts* is the detail's ``[{"name", "size"}]``."""
    size = next((a.get("size") for a in artifacts or () if a.get("name") == OUTPUT_LOG_PATH), None)
    if not isinstance(size, int):
        return None
    length = min(size, TAIL_BYTES)
    data = storage.read_range(app_name, verstr, OUTPUT_LOG_PATH, size - length, length)
    if data is None:
        return None
    cut = size > length
    if cut and b"\n" in data:
        data = data[data.index(b"\n") + 1:]  # the first line began before the range
    lines = data.decode("utf-8", "replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return {"lines": [_shown(line) for line in lines[-TAIL_LINES:]],
            "truncated": cut or len(lines) > TAIL_LINES}


def _total(params):
    for name in _TOTAL_PARAMS:
        value = (params or {}).get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def last_step(log, params):
    """``{"step", "of"}`` of the run's highest logged step, or None."""
    step = log.last_step()
    return None if step is None else {"step": step, "of": _total(params)}


def failure_fields(storage, app_name, verstr, detail, log, last_good=None):
    """The K4 fields of *detail* (a run detail being built over the parsed
    *log*), or {} unless the run failed or is stuck. *last_good(verstr)*
    answers from the app's index (None without one)."""
    if (detail.get("status") or {}).get("status") not in FAILURE_STATUSES:
        return {}
    return {
        "output_tail": output_tail(storage, app_name, verstr, detail.get("artifacts")),
        "last_step": last_step(log, detail.get("params")),
        "last_good": last_good(verstr) if last_good else None,
    }
