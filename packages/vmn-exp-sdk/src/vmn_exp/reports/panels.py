"""What a report body's ``vmn-panel`` blocks point at (plan 13 §4, §8.2)."""
import re

import yaml

_PANEL_RE = re.compile(r"^```vmn-panel[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)


def _spec(text):
    try:
        spec = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return spec if isinstance(spec, dict) and isinstance(spec.get("app"), str) else None


def _pinned(runs):
    if isinstance(runs, dict) and isinstance(runs.get("verstrs"), list):
        return [str(v) for v in runs["verstrs"]]
    return None


def panel_refs(body):
    """``[(app, [pinned verstrs] or None for a query panel)]`` of *body*'s
    parseable panels, in order."""
    specs = filter(None, (_spec(m.group(1)) for m in _PANEL_RE.finditer(body or "")))
    return [(spec["app"], _pinned(spec.get("runs"))) for spec in specs]
