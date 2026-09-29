"""The median rule's view of a trial's target metric: a finished trial's
series is read once, a running one again only once its log grew."""
from vmn_exp.core.sweep import peer_points
from vmn_exp.core.sweep.peer_points import PeerPoints, metric_points
from vmn_exp.core.writer import append_to_log, create_log_entry
from vmn_exp.storage.open import open_storage

APP = "my_app"


def _storage(tmp_path):
    return open_storage(None, str(tmp_path), subdir="experiments")


def _log(storage, verstr, step, **values):
    append_to_log(storage, APP, verstr, create_log_entry("metrics", step=step, values=values))


def _counting_loads(monkeypatch):
    loads = []
    real = peer_points.load_log

    def counting(storage, app_name, verstr):
        loads.append(verstr)
        return real(storage, app_name, verstr)

    monkeypatch.setattr(peer_points, "load_log", counting)
    return loads


def test_metric_points_reads_the_target_metric_only():
    log = [
        {"type": "metrics", "step": 1, "values": {"loss": 3.0, "acc": 0.1}},
        {"type": "note", "text": "x"},
        {"type": "metrics", "values": {"acc": 0.2}},
        {"type": "metrics", "values": {"loss": 2.0}},
    ]
    assert metric_points(log, "loss") == [(1, 3.0), (2, 2.0)]


def test_a_finished_trial_is_read_once(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    storage.save(APP, "v1", {"verstr": "v1"}, {})
    _log(storage, "v1", 1, loss=1.0)
    loads = _counting_loads(monkeypatch)
    points = PeerPoints(storage, APP, "loss")
    assert points.of("v1", finished=True) == [(1, 1.0)]
    _log(storage, "v1", 2, loss=0.5)  # cannot happen to a finished run
    assert points.of("v1", finished=True) == [(1, 1.0)]
    assert loads == ["v1"]


def test_a_running_trial_is_read_again_only_after_it_logged(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    storage.save(APP, "v1", {"verstr": "v1"}, {})
    _log(storage, "v1", 1, loss=1.0)
    loads = _counting_loads(monkeypatch)
    points = PeerPoints(storage, APP, "loss")
    assert points.of("v1") == [(1, 1.0)]
    assert points.of("v1") == [(1, 1.0)]
    assert loads == ["v1"]
    _log(storage, "v1", 2, loss=0.5)
    assert points.of("v1") == [(1, 1.0), (2, 0.5)]
    assert loads == ["v1", "v1"]
