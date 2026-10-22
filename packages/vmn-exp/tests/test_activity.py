"""Background activities (index refreshes, journal ticks, warm-ups) record
how often they ran, which one runs now and on which thread, how long they
take and how the last one failed, for the diagnostic dump."""
import threading
import time
import uuid

import pytest

from vmn_exp.core.activity import activity, background_section


def _name():
    return f"test activity {uuid.uuid4().hex[:8]}"


def entry(name, key=None):
    found = [a for a in background_section()["activities"]
             if a["name"] == name and a["key"] == key]
    return found[0] if found else None


def test_an_activity_counts_its_runs_and_durations():
    name = _name()
    with activity(name, key="ws"):
        time.sleep(0.02)
    with activity(name, key="ws"):
        pass
    got = entry(name, "ws")
    assert got["runs"] == 2
    assert got["running"] == []
    assert got["max_sec"] >= 0.02
    assert got["last_sec"] < got["max_sec"]
    assert got["last_ok_ago_sec"] >= 0
    assert got["last_error"] is None


def test_keys_are_separate_entries():
    name = _name()
    with activity(name, key="a"):
        pass
    assert entry(name, "a")["runs"] == 1
    assert entry(name, "b") is None
    assert entry(name) is None


def test_a_failure_is_recorded_and_raised():
    name = _name()
    with pytest.raises(RuntimeError):
        with activity(name):
            raise RuntimeError("store unreachable")
    got = entry(name)
    assert got["runs"] == 1
    assert "store unreachable" in got["last_error"]["error"]
    assert got["last_error"]["at"].endswith("Z")
    assert got["last_error"]["ago_sec"] >= 0
    assert got["last_ok_ago_sec"] is None


def test_a_running_activity_names_its_thread_and_age_longest_first():
    name, short = _name(), _name()
    started, release = threading.Event(), threading.Event()

    def work():
        with activity(name, key="ws"):
            started.set()
            release.wait(10)

    thread = threading.Thread(target=work, name="vmn-ui-journal", daemon=True)
    thread.start()
    assert started.wait(5)
    time.sleep(0.02)
    try:
        with activity(short):
            listed = [a["name"] for a in background_section()["activities"]
                      if a["name"] in (name, short)]
            assert listed == [name, short]
            running = entry(name, "ws")["running"]
            assert [r["thread"] for r in running] == ["vmn-ui-journal"]
            assert running[0]["running_sec"] >= 0.02
    finally:
        release.set()
        thread.join(5)
    assert entry(name, "ws")["running"] == []
