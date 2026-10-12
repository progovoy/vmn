"""How ``vmn-exp similar`` and the submission hint print similar runs.

``similar`` prints one line per result (``<app>/<verstr>`` with ``--all-apps``)::

    <verstr>  <score>  <author or ->  <age>  <status>  <goal metric>=<value>  — <reasons>  (+N runs)

``—`` standing in for a group without a goal metric value, ``(+N runs)`` for
the other runs of its group (a sweep, or repeats of one code). The hint
leads with the best of the closest runs on their goal metric::

    3 similar runs: best val_loss=0.31 — <verstr> by alice@x.io, 3w ago (<reasons>)
      <verstr> by bob@x.io, 2d ago (<reasons>)
"""
import datetime
import sys

from vmn_exp.cli.views import dumps, format_number, plural
from vmn_exp.core.status import parse_iso

NO_VALUE = "—"
_AGE_UNITS = ((365 * 86400, "y"), (30 * 86400, "mo"), (7 * 86400, "w"), (86400, "d"),
              (3600, "h"), (60, "m"))


def age(timestamp, now=None):
    """``3w ago``: how long ago *timestamp* (ISO-8601) was, in its largest
    whole unit; ``-`` when it is no time."""
    when = parse_iso(timestamp)
    if when is None:
        return "-"
    now = now or datetime.datetime.now(datetime.timezone.utc)
    seconds = max(0, int((now - when).total_seconds()))
    for size, unit in _AGE_UNITS:
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return f"{seconds}s ago"


def goal_text(goal):
    return f"{goal['metric']}={format_number(goal['value'])}" if goal else NO_VALUE


def item_line(item, with_app=False, now=None):
    """One result line (see the module docstring)."""
    label = f"{item['app']}/{item['verstr']}" if with_app else item["verstr"]
    fields = [label, f"{item['score']:.2f}", item.get("author") or "-",
              age(item.get("timestamp"), now), item.get("status") or "-",
              goal_text(item.get("goal"))]
    line = "  ".join(fields)
    if item.get("reasons"):
        line += "  — " + ", ".join(item["reasons"])
    others = item.get("group_size", 1) - 1
    if others > 0:
        line += f"  (+{plural(others, 'run')})"
    return line


def print_items(items, app_name, as_json=False, with_app=False):
    """``similar``'s output: the JSON items, else one line each — or, with
    none, a note on stderr."""
    if as_json:
        print(dumps(items))
        return
    if not items:
        print(f"No similar runs found for {app_name}", file=sys.stderr)
    for item in items:
        print(item_line(item, with_app))


def _best(items):
    """The best item on the goal metric of the closest item that has one,
    else the closest."""
    goals = [item for item in items if item.get("goal")]
    if not goals:
        return items[0]
    metric, direction = goals[0]["goal"]["metric"], goals[0]["goal"]["goal"]
    same = [item for item in goals if item["goal"]["metric"] == metric]
    return (min if direction == "min" else max)(same, key=lambda i: i["goal"]["value"])


def _who(item, now):
    text = item["verstr"] + (f" by {item['author']}" if item.get("author") else "")
    text += f", {age(item.get('timestamp'), now)}"
    return text + (f" ({', '.join(item['reasons'])})" if item.get("reasons") else "")


def hint_lines(items, now=None):
    """The submission hint's lines for *items* (none for no item)."""
    if not items:
        return []
    best = _best(items)
    lead = f"best {goal_text(best['goal'])}" if best.get("goal") else "closest"
    lines = [f"{plural(len(items), 'similar run')}: {lead} — {_who(best, now)}"]
    return lines + [f"  {_who(item, now)}" for item in items if item is not best]
