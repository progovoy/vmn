"""Report panel spec (``vmn-panel`` blocks): parse, validate, JSON Schema.

Pure: validation never raises for a bad spec, it returns a ``PanelResult``
carrying the error so the rest of a report still renders.
"""

import json
import re
from dataclasses import dataclass

import yaml

from vmn_exp.core.query import QueryError, compile_query

SPEC_VERSION = 1

# Field kinds -> JSON Schema fragments; the validator checks the same kinds.
_KIND_SCHEMAS = {
    "str": {"type": "string"},
    "bool": {"type": "boolean"},
    "unit": {"type": "number", "minimum": 0, "maximum": 1},
    "posint": {"type": "integer", "minimum": 1},
    "strlist": {"type": "array", "items": {"type": "string"}},
    "step": {"oneOf": [{"type": "integer", "minimum": 0}, {"const": "last"}]},
    "x": {
        "type": "object",
        "properties": {
            "mode": {"enum": ["step", "wall", "relative", "metric"]},
            "metric": {"type": "string"},
        },
        "required": ["mode"],
        "additionalProperties": False,
        "if": {"properties": {"mode": {"const": "metric"}}},
        "then": {"required": ["mode", "metric"]},
    },
}

# type -> ({field: kind}, required fields, single-run)
PANEL_TYPES = {
    "curves": ({"keys": "strlist", "x": "x", "smoothing": "unit", "log_y": "bool",
                "max_points": "posint"}, ("keys",), False),
    "leaderboard": ({"columns": "strlist", "params": "strlist"}, (), False),
    "bar": ({"metric": "str"}, ("metric",), False),
    "scatter": ({"x": "str", "y": "str"}, ("x", "y"), False),
    "parallel": ({"columns": "strlist"}, ("columns",), False),
    "importance": ({"metric": "str"}, ("metric",), False),
    "grouped": ({"group_by": "str", "metric": "str"}, ("group_by", "metric"), False),
    "media": ({"key": "str", "step": "step"}, ("key",), True),
    "table": ({"path": "str"}, ("path",), True),
    "histogram": ({"key": "str"}, ("key",), True),
    "lineage": ({"depth": "posint"}, (), True),
    "run": ({}, (), True),
}

_COMMON = {"v": None, "id": "str", "type": None, "app": "str", "runs": None,
           "title": "str", "height": "posint"}
_REQUIRED = ("v", "id", "type", "app", "runs")
_QUERY_RUNS = {"query": "str", "sort": "str", "order": None, "limit": "posint",
               "archived": "bool"}


@dataclass(frozen=True)
class PanelResult:
    spec: object = None
    error: str = None
    query_offset: int = None

    @property
    def ok(self):
        return self.error is None


class _Invalid(Exception):
    def __init__(self, message, offset=None):
        super().__init__(message)
        self.offset = offset


def _is_kind(value, kind):
    if kind == "str":
        return isinstance(value, str)
    if kind == "bool":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if kind == "unit":
        return isinstance(value, (int, float)) and 0 <= value <= 1
    if kind == "posint":
        return isinstance(value, int) and value >= 1
    if kind == "strlist":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if kind == "step":
        return value == "last" or (isinstance(value, int) and value >= 0)
    if kind == "x":
        return _is_x(value)
    raise AssertionError(kind)


def _is_x(value):
    if not isinstance(value, dict) or set(value) - {"mode", "metric"}:
        return False
    if value.get("mode") not in ("step", "wall", "relative", "metric"):
        return False
    if "metric" in value and not isinstance(value["metric"], str):
        return False
    return value["mode"] != "metric" or "metric" in value


def _check_fields(mapping, kinds, where):
    for name, value in mapping.items():
        if name not in kinds:
            raise _Invalid(f"unknown field {where}{name!r}")
        kind = kinds[name]
        if kind and not _is_kind(value, kind):
            raise _Invalid(f"field {where}{name!r} must be {kind}")


def _check_query(text):
    try:
        compile_query(text)
    except QueryError as exc:
        match = re.search(r"at offset (\d+)", str(exc))
        raise _Invalid(f"runs.query: {exc}", int(match.group(1)) if match else None)


def _check_runs(runs, single):
    if not isinstance(runs, dict):
        raise _Invalid("runs must be a mapping")
    if "verstrs" in runs:
        if set(runs) != {"verstrs"}:
            raise _Invalid("runs takes either verstrs or a query, not both")
        verstrs = runs["verstrs"]
        if not _is_kind(verstrs, "strlist") or not verstrs:
            raise _Invalid("runs.verstrs must be a non-empty list of strings")
        if single and len(verstrs) != 1:
            raise _Invalid("this panel type needs exactly one run in runs.verstrs")
        return
    if single:
        raise _Invalid("this panel type needs exactly one run in runs.verstrs")
    if "query" not in runs:
        raise _Invalid("runs needs verstrs or query")
    _check_fields(runs, _QUERY_RUNS, "runs.")
    if runs.get("order", "desc") not in ("asc", "desc"):
        raise _Invalid("runs.order must be asc or desc")
    _check_query(runs["query"])


def _check(spec):
    if not isinstance(spec, dict):
        raise _Invalid("panel spec must be a mapping")
    missing = [name for name in _REQUIRED if name not in spec]
    if missing:
        raise _Invalid(f"missing field(s): {', '.join(missing)}")
    if spec["v"] != SPEC_VERSION or isinstance(spec["v"], bool):
        raise _Invalid(f"unsupported panel spec version {spec['v']!r}")
    kind = spec["type"]
    if not isinstance(kind, str) or kind not in PANEL_TYPES:
        raise _Invalid(f"unknown panel type {kind!r}")
    fields, required, single = PANEL_TYPES[kind]
    _check_fields(spec, {**_COMMON, **fields}, "")
    absent = [name for name in required if name not in spec]
    if absent:
        raise _Invalid(f"{kind} panel needs field(s): {', '.join(absent)}")
    _check_runs(spec["runs"], single)


def validate_panel(spec):
    """Validate a decoded panel dict; never raises for a bad spec."""
    try:
        _check(spec)
    except _Invalid as exc:
        return PanelResult(spec=spec, error=str(exc), query_offset=exc.offset)
    return PanelResult(spec=spec)


def parse_panel(text):
    """Decode a ``vmn-panel`` block body (YAML, so JSON too) and validate it."""
    try:
        spec = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return PanelResult(error=f"invalid YAML: {exc}")
    return validate_panel(spec)


def _props(kinds):
    return {name: _KIND_SCHEMAS[kind] for name, kind in kinds.items() if kind}


def _runs_schema(single):
    pinned = {
        "type": "object",
        "properties": {"verstrs": {**_KIND_SCHEMAS["strlist"], "minItems": 1}},
        "required": ["verstrs"],
        "additionalProperties": False,
    }
    if single:
        pinned["properties"]["verstrs"]["maxItems"] = 1
        return pinned
    live = {
        "type": "object",
        "properties": {**_props(_QUERY_RUNS), "order": {"enum": ["asc", "desc"]}},
        "required": ["query"],
        "additionalProperties": False,
    }
    return {"oneOf": [pinned, live]}


def _type_schema(kind):
    fields, required, single = PANEL_TYPES[kind]
    props = {
        **_props(_COMMON),
        "v": {"const": SPEC_VERSION},
        "type": {"const": kind},
        "runs": _runs_schema(single),
        **_props(fields),
    }
    return {
        "type": "object",
        "properties": props,
        "required": [*_REQUIRED, *required],
        "additionalProperties": False,
    }


def json_schema():
    """JSON Schema of every v1 panel type (committed for the webui)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "vmn-panel",
        "oneOf": [_type_schema(kind) for kind in PANEL_TYPES],
    }


if __name__ == "__main__":
    print(json.dumps(json_schema(), indent=2))
