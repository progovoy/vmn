"""`pip install "vmn-exp[ui]"` works on a free-threaded Python: the ``ui`` extra
pulls in nothing without free-threaded wheels (orjson has none, so pip builds it
from source, which needs Rust). orjson stays an opt-in extra: the ui renders
JSON with the standard library without it."""
import pathlib
import re

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib

PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def _extras():
    return tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]


def _names(requirements):
    return {re.split(r"[\s<>=!~;\[]", req, maxsplit=1)[0].lower() for req in requirements}


def test_the_ui_extra_needs_no_orjson():
    assert "orjson" not in _names(_extras()["ui"])


def test_orjson_is_its_own_extra():
    assert _names(_extras()["orjson"]) == {"orjson"}
