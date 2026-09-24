"""parse_json_line: exactly ``json.loads`` of the stripped line, kept only
when it is an object — whatever parser does the work."""
import json
import math

import pytest

from version_stamp.core.experiment_logfiles import parse_json_line


def _reference(line):
    line = line.strip()
    if not line:
        return None
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None


LINES = [
    '{"a": 1}',
    '  {"a": 1}  \t',
    '{"a": NaN, "b": Infinity, "c": -Infinity}',
    '{"big": 123456789012345678901234567890, "neg": -9223372036854775809}',
    '{"u64": 18446744073709551615, "f": 1e400, "tiny": 5e-324}',
    '{"s": "\\ud800", "e": "\\ud83d\\ude00", "z": "\\u0000", "n": "café"}',
    '{"a": 1, "a": 2}',
    '{"a": 1} {"b": 2}',
    '{"a": 1} x',
    '{"a": 1} ',
    ' {"a": 1}',
    '﻿{"a": 1}',
    '[1, 2]',
    '"text"',
    '42',
    'null',
    '',
    '   ',
    'not json',
    '{"a": ',
    '{"nested": {"deep": [1, {"x": null}]}, "t": true, "f": false}',
    '{"x": -0, "y": -0.0, "z": 1E5, "w": 0.1000000000000000055511151231257827}',
]


def _same(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return repr(a) == repr(b)


@pytest.mark.parametrize("line", LINES)
def test_a_line_parses_exactly_like_json_loads(line):
    assert _same(parse_json_line(line), _reference(line))
