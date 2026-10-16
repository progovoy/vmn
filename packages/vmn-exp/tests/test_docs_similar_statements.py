"""What the similar-runs docs (plan 18) say about the code is what the code
does: whose conf weights score, which ``hypothesis`` is text, what warms the
hint's index, and why ``similar`` without a ref compares the working tree."""
import os
import re

import pytest
import vmn_exp.cli.similar as similar_cli
from exp_helpers import _PROJECT_ROOT
from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.core.fold import fold_hypothesis, fold_log
from vmn_exp.core.writer import create_log_entry
from vmn_exp.sdk.reader import similar_runs

EXPERIMENTS = "docs/vmn-exp/experiments.md"
PLAN = "docs/plans/18-similar-runs.md"
TARGET_WEIGHTS = "under the target app's"
NO_REF_EXCEPTION = "the one action whose missing ref means the working tree"


def _read(relpath):
    with open(os.path.join(_PROJECT_ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def _flat(text):
    return re.sub(r"\s+", " ", text)


def _section(relpath, heading):
    """*heading*'s section of *relpath*, flattened: up to the next heading of
    its level or above (``#`` lines inside code blocks are not headings)."""
    level = len(heading) - len(heading.lstrip("#"))
    lines, fenced, found = [], False, False
    for line in _read(relpath).splitlines():
        if line.startswith("```"):
            fenced = not fenced
        is_heading = not fenced and re.match(rf"#{{1,{level}}} ", line)
        if found and is_heading:
            break
        found = found or line == heading
        if found:
            lines.append(line)
    assert found, (relpath, heading)
    return _flat("\n".join(lines))


def test_the_docs_say_the_target_apps_weights_score_every_app_searched():
    ui = _section("docs/vmn-exp/ui.md", "### Similar runs")
    sdk = _section("docs/vmn-exp/sdk.md", "### Similar runs")
    cli = _section(EXPERIMENTS, "### `similar`")
    for text in (ui, sdk, cli, _flat(similar_runs.__doc__)):
        assert TARGET_WEIGHTS in text
    assert "each app's conf `experiment.similar.weights`" not in ui
    assert "a text query on its text alone" in ui
    assert "each app's metrics schema and `experiment.similar.weights`" not in sdk


def test_only_a_create_or_run_hypothesis_is_text_and_the_docs_say_so():
    create = {"type": "create", "timestamp": "2026-01-01T00:00:00Z"}
    added = create_log_entry("structured", hypothesis="focal loss for imbalance")
    assert fold_hypothesis(fold_log([create, added])) is None
    assert fold_hypothesis(fold_log([dict(create, hypothesis="focal")])) == "focal"

    intent = _section(EXPERIMENTS, "### Intent: what a run is for")
    structured = _section(EXPERIMENTS, "## Structured notes & params")
    signals = _section(EXPERIMENTS, "### `similar`")
    assert "On `create`/`run`, `-f`'s" in intent and "(not `add -f`'s" in intent
    assert "(not `add -f`'s" in structured
    assert "`create`/`run -f`'s `hypothesis`" in signals


def test_the_hint_docs_name_what_warms_its_index_and_not_the_ui():
    hint = _section(EXPERIMENTS, "#### The submission hint")
    assert "`vmn-exp ui` last refreshed" not in hint
    assert "as `list`, `show`, `compare`, `similar`" in hint
    assert "`vmn-exp ui` keeps its own index" in hint


def _version_help(capsys):
    with pytest.raises(SystemExit) as exc:
        vmn_exp_run(["similar", "--help"])
    assert exc.value.code == 0
    out = _flat(capsys.readouterr().out)
    start = out.index("-v VERSION, --version VERSION")
    return out[start:out.index("--note NOTE", start)]


def test_the_similar_docs_call_the_working_tree_default_the_one_exception(capsys):
    texts = {
        "help": _version_help(capsys),
        "cli/similar.py": _flat(similar_cli.__doc__),
        EXPERIMENTS: _section(EXPERIMENTS, "### `similar`"),
        PLAN: _section(PLAN, "### 3.4 Surfaces"),
    }
    for where, text in texts.items():
        assert "snapshot diff" not in text, where
        assert NO_REF_EXCEPTION in text, where
