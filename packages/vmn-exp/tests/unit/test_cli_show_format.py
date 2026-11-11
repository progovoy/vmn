"""``vmn-exp show`` log lines: one description per log entry type."""
import pytest

from vmn_exp.cli.experiment import _describe_log_entry


@pytest.mark.parametrize("entry, text", [
    ({"type": "metrics", "values": {"loss": 0.5, "acc": 1}}, "metrics: loss=0.5, acc=1"),
    ({"type": "params", "params": {"lr": 0.1}}, "params: lr=0.1"),
    ({"type": "error", "exception": "ValueError", "message": "bad"}, "error: ValueError: bad"),
    ({"type": "note", "text": "hi"}, "note: hi"),
    ({"type": "alert", "title": "slow", "level": "warn", "text": "t"}, "alert [warn]: slow: t"),
    ({"type": "alert", "title": "slow"}, "alert [info]: slow"),
    ({"type": "artifact", "path": "m.pt", "size": 3}, "artifact: m.pt (3 bytes)"),
    ({"type": "image", "name": "s", "step": 0, "path": "p.png"}, "image: s @ step 0 (p.png)"),
    ({"type": "create", "note": "go"}, "created: go"),
    ({"type": "create"}, "created"),
    ({"type": "intent"}, "intent"),
    ({}, "?"),
])
def test_describe_log_entry_for_each_entry_type(entry, text):
    assert _describe_log_entry(entry) == text
