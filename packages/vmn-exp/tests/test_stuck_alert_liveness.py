"""Plan 32 F11: the stuck alert dates its transition from the same liveness
time the stuck status is derived from — the fresher of the writer's heartbeat
and the store's write time of ``run_state.yml`` — so a run that reads stuck
alerts, and its message never claims a heartbeat that never came. Pure."""
import datetime

from vmn_exp.core import status as st
from vmn_exp.core.alerts import transitions as tr

NOW = datetime.datetime(2026, 11, 7, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _ago(seconds):
    return NOW - datetime.timedelta(seconds=seconds)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _stuck(heartbeat_age=None, started_age=7200):
    return {
        "state": "running", "host": "gpu-7", "pid": 4242,
        "started_at": _iso(_ago(started_age)),
        "heartbeat": None if heartbeat_age is None else _iso(_ago(heartbeat_age)),
        "heartbeat_interval_sec": 30, "exit_code": None,
    }


class _Snap:
    def __init__(self, verstr, run_state, observed_at):
        self.run_states = {verstr: run_state}
        self.run_state_observed_at = {verstr: observed_at}

    def row(self, verstr):
        return {"name": None}


class _Storage:
    def __init__(self):
        self.files = {}

    def load_file(self, app_name, verstr, name):
        return self.files.get((verstr, name))

    def save_file(self, app_name, verstr, name, data):
        self.files[(verstr, name)] = data


class _Alerter:
    def __init__(self):
        self.sent = []

    def wants(self, status):
        return status == st.STUCK

    def send(self, alert):
        self.sent.append(alert)
        return True


def _watch(monkeypatch, run_state, observed_at, within_sec, now=NOW, storage=None):
    snap = _Snap("0.0.1-dev.1", run_state, observed_at)
    monkeypatch.setattr(tr.experiment_index, "indexed_snapshot", lambda *a, **k: snap)
    alerter = _Alerter()
    fired = tr.watch_app(storage or _Storage(), "app", alerter, within_sec, now=now)
    return fired, alerter


def test_last_alive_at_is_the_fresher_of_heartbeat_and_store_write():
    state = _stuck(heartbeat_age=86400)
    assert st.last_alive_at(state, now=NOW) == _ago(86400)
    assert st.last_alive_at(state, now=NOW, observed_at=_ago(600)) == _ago(600)
    assert st.last_alive_at(_stuck(heartbeat_age=60), now=NOW, observed_at=_ago(600)) == _ago(60)


def test_last_alive_at_falls_back_to_the_start_before_the_first_beat():
    assert st.last_alive_at(_stuck(started_age=900), now=NOW) == _ago(900)


def test_last_alive_at_ignores_a_heartbeat_from_the_future_against_the_store():
    state = _stuck(heartbeat_age=-3600)
    assert st.last_alive_at(state, now=NOW, observed_at=_ago(600)) == _ago(600)


def test_a_run_stuck_by_its_store_time_alerts_within_the_window(monkeypatch):
    """Heartbeat a day old (writer clock behind), store write 10 min ago: the
    status is stuck since 10 min, so a 1h watch window must alert it."""
    state, observed = _stuck(heartbeat_age=86400), _ago(600)
    assert st.derive_status(state, now=NOW, observed_at=observed) == st.STUCK
    fired, alerter = _watch(monkeypatch, state, observed, within_sec=3600)
    assert fired == [("0.0.1-dev.1", st.STUCK)]
    assert alerter.sent[0]["text"].startswith("no heartbeat for 600s")


def test_the_stuck_key_is_the_liveness_time():
    state, observed = _stuck(heartbeat_age=86400), _ago(600)
    assert tr.transition_key(st.STUCK, state, observed_at=observed) == (
        f"stuck@{_iso(_ago(600))}"
    )
    assert tr.transition_key(st.STUCK, state) == f"stuck@{_iso(_ago(86400))}"


def test_a_run_that_never_beat_says_so():
    alert = tr.transition_alert("app", "0.0.1-dev.1", _stuck(started_age=900), st.STUCK, now=NOW)
    assert alert["text"].startswith("no heartbeat since start (900s ago)")
    assert "no heartbeat for" not in alert["text"]


def test_the_stuck_key_judges_a_future_heartbeat_by_the_watch_time(monkeypatch):
    """watch_app(now=T): a heartbeat after T (but before the wall clock) is the
    writer's clock ahead of T, so the stuck status and its key both date the
    transition from the store write — the key must not consult the wall clock."""
    watch_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    observed = watch_at - datetime.timedelta(seconds=600)
    state = dict(_stuck(), heartbeat=_iso(watch_at + datetime.timedelta(seconds=60)))
    assert st.derive_status(state, now=watch_at, observed_at=observed) == st.STUCK
    storage = _Storage()
    _watch(monkeypatch, state, observed, 3600, now=watch_at, storage=storage)
    [key] = tr.load_sent(storage, "app", "0.0.1-dev.1")
    assert st.parse_iso(key.split("@", 1)[1]) == observed
