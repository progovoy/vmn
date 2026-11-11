"""``define_metric`` takes only its named keywords (plan 41 D8): a typo like
``gaol="min"`` is a TypeError on a real run and on a NoOpRun alike."""
import pytest

from vmn_exp.sdk.metric_defs import MetricDefinitions
from vmn_exp.sdk.ranks import NoOpRun


class _RecordingRun(MetricDefinitions):
    def __init__(self):
        self.entries = []

    def _append(self, entry):
        self.entries.append(entry)


def test_unknown_keyword_raises_type_error_and_appends_nothing():
    run = _RecordingRun()

    with pytest.raises(TypeError, match="gaol"):
        run.define_metric("val_loss", gaol="min")

    assert run.entries == []


def test_known_keywords_produce_the_same_entry_as_before():
    run = _RecordingRun()

    run.define_metric(
        "val_*", step_metric="epoch", summary="last", goal="min", hidden=True, chart="bars",
    )

    (entry,) = run.entries
    entry.pop("timestamp")
    assert entry == {
        "type": "define_metric",
        "name": "val_*",
        "summary": "last",
        "goal": "min",
        "hidden": True,
        "chart": "bars",
        "step_metric": "epoch",
    }


def test_noop_run_rejects_the_same_unknown_keyword():
    with pytest.raises(TypeError, match="gaol"):
        NoOpRun().define_metric("val_loss", gaol="min")
