"""start_run takes app_name positionally and everything else by keyword (plan 41 D5)."""

import ast
import inspect
from pathlib import Path

import pytest

from vmn_exp.sdk import start_run

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_start_run_extra_positional_raises_type_error():
    with pytest.raises(TypeError):
        start_run("app", "note", mode="disabled")


def test_start_run_app_name_positional_still_works():
    run = start_run("app", mode="disabled")
    run.finish()


def test_signature_shows_keyword_only():
    params = list(inspect.signature(start_run).parameters.values())
    assert params[0].name == "app_name"
    assert params[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    not_keyword_only = [p.name for p in params[1:] if p.kind is not inspect.Parameter.KEYWORD_ONLY]
    assert not_keyword_only == []


def _calls_with_extra_positionals(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name == "start_run" and len(node.args) > 1:
            yield node.lineno


def test_no_source_call_passes_start_run_more_than_one_positional():
    offenders = []
    for path in sorted(REPO_ROOT.glob("packages/*/src/**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [f"{path.relative_to(REPO_ROOT)}:{line}" for line in _calls_with_extra_positionals(tree)]
    assert offenders == []
