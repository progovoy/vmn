"""`vmn exp prune --query`: select candidates via the experiment query language.

Semantics (decision D17):
- dry-run unless ``--yes``/``-y`` is passed
- ``--dry-run`` beats ``--yes``
- empty query → error
- invalid query → error (QueryError message, non-zero exit)
- ``--keep N`` / ``--older-than`` apply WITHIN the query scope
- ``-v`` is rejected together with ``--query``
- all existing protections still apply (running/stuck, protect-tag, ancestors)
- preview lists at most 20 runs, then "... and N more"
"""
import yaml
import pytest
from helpers import _bootstrap, _exp, _storage
from version_stamp.core.utils import now_iso


# ---- helpers ----------------------------------------------------------------


def _create(app_layout, *extra):
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


def _verstrs(app_layout):
    return [
        m["verstr"]
        for m in _storage(app_layout).list_snapshots(app_layout.app_name)
    ]


def _mark_failed(app_layout, verstr):
    state = {
        "state": "failed",
        "pid": 1,
        "host": "h",
        "started_at": now_iso(),
        "heartbeat": now_iso(),
        "heartbeat_interval_sec": 30,
        "exit_code": 1,
    }
    _storage(app_layout).save_file(
        app_layout.app_name, verstr, "run_state.yml", yaml.dump(state)
    )


def _mark_running(app_layout, verstr):
    state = {
        "state": "running",
        "pid": 1,
        "host": "h",
        "started_at": now_iso(),
        "heartbeat": now_iso(),
        "heartbeat_interval_sec": 30,
        "exit_code": None,
    }
    _storage(app_layout).save_file(
        app_layout.app_name, verstr, "run_state.yml", yaml.dump(state)
    )


def _tag(app_layout, verstr, *pairs):
    assert _exp(app_layout.app_name, action="tag", extra_args=[verstr, *pairs]) == 0


def _prune_q(app_layout, capfd, query, *extra):
    capfd.readouterr()
    err = _exp(
        app_layout.app_name, action="prune", extra_args=["--query", query, *extra]
    )
    return err, capfd.readouterr().out


# ---- tests ------------------------------------------------------------------


def test_query_defaults_to_dry_run(app_layout, capfd):
    """--query without --yes is a preview: runs are not deleted."""
    _bootstrap(app_layout)
    a = _create(app_layout)
    _mark_failed(app_layout, a)

    err, out = _prune_q(app_layout, capfd, 'status = "failed"')
    assert err == 0, out
    assert _verstrs(app_layout) == [a]
    assert "Would delete" in out


def test_query_yes_deletes_only_matches(app_layout, capfd):
    """--query --yes deletes only matching runs, not all."""
    _bootstrap(app_layout)
    a = _create(app_layout)
    b = _create(app_layout)
    _mark_failed(app_layout, a)

    err, out = _prune_q(app_layout, capfd, 'status = "failed"', "--yes")
    assert err == 0, out
    assert _verstrs(app_layout) == [b]
    assert a in out


def test_query_by_tag(app_layout, capfd):
    """Filter candidates by a tag value."""
    _bootstrap(app_layout)
    a = _create(app_layout)
    b = _create(app_layout)
    _tag(app_layout, a, "env=test")

    err, out = _prune_q(app_layout, capfd, 'tags.env = "test"', "--yes")
    assert err == 0, out
    assert _verstrs(app_layout) == [b]
    assert a in out


def test_query_by_status_failed(app_layout, capfd):
    """status = "failed" selects only the failed run."""
    _bootstrap(app_layout)
    a = _create(app_layout)
    b = _create(app_layout)
    _mark_failed(app_layout, a)

    err, out = _prune_q(app_layout, capfd, 'status = "failed"', "--yes")
    assert err == 0, out
    remaining = _verstrs(app_layout)
    assert b in remaining
    assert a not in remaining


def test_query_rejects_v(app_layout, capfd):
    """--query and -v are mutually exclusive."""
    _bootstrap(app_layout)
    a = _create(app_layout)

    capfd.readouterr()
    err = _exp(
        app_layout.app_name,
        action="prune",
        version=a,
        extra_args=["--query", 'status = "failed"'],
    )
    assert err == 1


def test_empty_query_errors(app_layout, capfd):
    """An empty --query string is an error."""
    _bootstrap(app_layout)
    _create(app_layout)

    capfd.readouterr()
    err = _exp(app_layout.app_name, action="prune", extra_args=["--query", ""])
    assert err == 1


def test_invalid_query_errors(app_layout, capfd):
    """A syntactically invalid query exits non-zero with a QueryError message."""
    _bootstrap(app_layout)
    _create(app_layout)

    capfd.readouterr()
    err = _exp(app_layout.app_name, action="prune", extra_args=["--query", "bad < >"])
    assert err == 1


def test_query_no_matches(app_layout, capfd):
    """Query matches nothing: 'Nothing to prune', run survives."""
    _bootstrap(app_layout)
    a = _create(app_layout)

    err, out = _prune_q(app_layout, capfd, 'status = "failed"')
    assert err == 0, out
    assert _verstrs(app_layout) == [a]
    assert "Nothing to prune" in out


def test_query_with_keep_keeps_newest_matches(app_layout, capfd):
    """--keep N within query scope: the N newest matching runs survive."""
    _bootstrap(app_layout)
    a = _create(app_layout)
    b = _create(app_layout)
    c = _create(app_layout)
    _tag(app_layout, a, "env=test")
    _tag(app_layout, b, "env=test")
    _tag(app_layout, c, "env=test")

    err, out = _prune_q(
        app_layout, capfd, 'tags.env = "test"', "--keep", "1", "--yes"
    )
    assert err == 0, out
    remaining = _verstrs(app_layout)
    assert c in remaining
    assert a not in remaining
    assert b not in remaining


def test_query_with_older_than_intersects(app_layout, capfd):
    """--older-than within query scope: fresh matching runs survive."""
    _bootstrap(app_layout)
    a = _create(app_layout)
    _mark_failed(app_layout, a)

    # a is failed but fresh; --older-than 1d keeps it
    err, out = _prune_q(
        app_layout, capfd, 'status = "failed"', "--older-than", "1d", "--yes"
    )
    assert err == 0, out
    assert _verstrs(app_layout) == [a]


def test_query_respects_running_and_protect_tag(app_layout, capfd):
    """Running guard and protect-tag guard apply within query results."""
    _bootstrap(app_layout)
    a = _create(app_layout)
    b = _create(app_layout)
    _tag(app_layout, a, "env=test")
    _tag(app_layout, b, "env=test")
    _mark_running(app_layout, a)

    err, out = _prune_q(
        app_layout, capfd, 'tags.env = "test"', "--protect-tag", "env", "--yes"
    )
    assert err == 0, out
    # a is running; b has protect-tag; neither deleted
    assert set(_verstrs(app_layout)) == {a, b}


def test_query_keeps_ancestor_of_kept_run(app_layout, capfd):
    """A query candidate that is an ancestor of a kept run is itself kept."""
    _bootstrap(app_layout)
    outer = _create(app_layout)
    inner = _create(app_layout, "--parent", outer)
    # Tag only the outer run for deletion; inner is not a candidate
    _tag(app_layout, outer, "prune=yes")

    err, out = _prune_q(app_layout, capfd, 'tags.prune = "yes"', "--yes")
    assert err == 0, out
    # outer kept because inner (a kept non-candidate) points to it as parent
    assert outer in _verstrs(app_layout)
    assert inner in _verstrs(app_layout)


def test_preview_truncates_after_20(app_layout, capfd):
    """Preview shows at most 20 lines, then '... and N more'."""
    _bootstrap(app_layout)
    runs = [_create(app_layout) for _ in range(25)]
    for r in runs:
        _mark_failed(app_layout, r)

    err, out = _prune_q(app_layout, capfd, 'status = "failed"')
    assert err == 0, out
    assert "Would delete 25" in out
    assert "... and 5 more" in out


def test_dry_run_beats_yes(app_layout, capfd):
    """--dry-run beats --yes: even with --yes, no deletion occurs."""
    _bootstrap(app_layout)
    a = _create(app_layout)
    _mark_failed(app_layout, a)

    err, out = _prune_q(
        app_layout, capfd, 'status = "failed"', "--dry-run", "--yes"
    )
    assert err == 0, out
    assert _verstrs(app_layout) == [a]
    assert "Would delete" in out
