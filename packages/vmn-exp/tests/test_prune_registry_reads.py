"""prune's registry guard reads the registry once per call, whatever the
batch of ``-v`` targets, and reads its objects concurrently (plan 31 §4.3:
~16k registry objects read one by one took ~15 min per call)."""
import threading
import time

from exp_helpers import _bootstrap, _exp, _storage

from vmn_exp.registry import view
from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.storage.local import LocalSnapshotStorage


class _Concurrency:
    """Wraps registry reads, each taking a little while, and records how many
    ran at once."""

    def __init__(self):
        self.calls, self.active, self.peak = 0, 0, 0
        self._lock = threading.Lock()

    def wrap(self, real):
        def reading(*args, **kwargs):
            with self._lock:
                self.calls += 1
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                time.sleep(0.02)
                return real(*args, **kwargs)
            finally:
                with self._lock:
                    self.active -= 1
        return reading


def _track(monkeypatch, *names):
    tracker = _Concurrency()
    for name in names:
        monkeypatch.setattr(view, name, tracker.wrap(getattr(view, name)))
    return tracker


def _registry(storage, models=3, versions=4):
    for m in range(models):
        ensure_model(storage, f"m{m}")
        for v in range(versions):
            register_version(storage, f"m{m}", {"app": "myapp", "verstr": f"0.0.{m}-r{v}"})


def test_registry_versions_are_read_concurrently(tmp_path, monkeypatch):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    _registry(storage)
    versions = _track(monkeypatch, "get_version")

    runs = view.registered_runs(storage)

    assert len(runs) == 12
    assert versions.calls == 12
    assert versions.peak > 1


def test_registry_models_are_read_concurrently(tmp_path, monkeypatch):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    _registry(storage, models=6, versions=1)
    models = _track(monkeypatch, "read_entries")

    assert len(view.registered_runs(storage)) == 6
    assert models.calls == 6
    assert models.peak > 1


def _create(app_layout):
    assert _exp(app_layout.app_name) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


def test_targeted_prune_reads_the_registry_once_whatever_the_batch(
        app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    runs = [_create(app_layout) for _ in range(4)]
    storage = _storage(app_layout)
    ensure_model(storage, "clf")
    for verstr in runs[:2]:
        register_version(storage, "clf", {"app": app_layout.app_name, "verstr": verstr})
    versions = _track(monkeypatch, "get_version")

    assert _exp(app_layout.app_name, action="prune", version=[runs[0]]) == 0
    one = versions.calls
    assert _exp(app_layout.app_name, action="prune", version=runs) == 0

    assert one == 2
    assert versions.calls - one == 2
    remaining = {m["verstr"] for m in _storage(app_layout).list_snapshots(app_layout.app_name)}
    assert remaining == set(runs[:2])
    assert "vmn-exp model delete" in capfd.readouterr().out
