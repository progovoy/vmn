"""Diff/export materialization clones deps and both diff sides concurrently,
yet results and log messages keep the serial, input-ordered sequence."""
import logging
import os
import time

import pytest

from version_stamp.core import logging as vmn_logging
from version_stamp.devversion import materialize

CLONE_SEC = 0.3


@pytest.fixture(autouse=True)
def _logger():
    vmn_logging.ensure_logger()


def _meta(tag):
    deps = {
        f"dep_{tag}_{i}": {"hash": f"{tag}{i}" * 20, "remote": f"https://h/{tag}{i}"}
        for i in (1, 2)
    }
    return {
        "base_commit": tag * 40,
        "remote": f"https://h/{tag}",
        "changesets": {".": {}, **deps},
    }


def _fake_clone(monkeypatch, failing=(), delays=None):
    """Clone stub: sleeps, writes the commit into dest; *failing* commits fail
    (after logging); *delays* overrides the sleep per commit."""
    calls = []

    def clone(dest, local_repo, remote, commit):
        calls.append(commit)
        time.sleep((delays or {}).get(commit, CLONE_SEC))
        if commit in failing:
            vmn_logging.VMN_LOGGER.error(f"clone of {commit[:2]} failed")
            return 1
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, "commit.txt"), "w") as f:
            f.write(commit + "\n")
        return 0

    monkeypatch.setattr(materialize, "_clone_at", clone)
    return calls


def _diff():
    return materialize.render_tree_diff(
        None, "v1", _meta("a"), {}, "v2", _meta("b"), {}
    )


def _messages(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_pair_and_deps_clone_concurrently(monkeypatch):
    calls = _fake_clone(monkeypatch)

    start = time.monotonic()
    text, err = _diff()
    elapsed = time.monotonic() - start

    assert err is None
    assert len(calls) == 6
    assert elapsed < 0.6 * len(calls) * CLONE_SEC
    for tag in ("a", "b"):
        assert tag * 40 in text
        for i in (1, 2):
            assert f"{tag}{i}" * 20 in text


def test_dep_failures_log_in_input_order(monkeypatch, caplog):
    # a later dep / side finishes first; messages still follow input order
    failing = {"a1" * 20, "a2" * 20, "b1" * 20}
    delays = {"a1" * 20: 0.5, "a2" * 20: 0.1, "a" * 40: 0.2, "b" * 40: 0.05}
    _fake_clone(monkeypatch, failing=failing, delays=delays)

    text, err = _diff()

    assert err is None
    assert _messages(caplog) == [
        "clone of a1 failed",
        "Failed to export dependency dep_a_1",
        "clone of a2 failed",
        "Failed to export dependency dep_a_2",
        "clone of b1 failed",
        "Failed to export dependency dep_b_1",
    ]
    assert "b2" * 20 in text


def test_first_side_failure_wins_like_serial(monkeypatch, caplog):
    _fake_clone(monkeypatch, failing={"a" * 40, "b" * 40}, delays={"a" * 40: 0.4})

    text, err = _diff()

    assert text is None
    assert err == "Failed to materialize snapshots for diff"
    assert _messages(caplog) == ["clone of aa failed"]
