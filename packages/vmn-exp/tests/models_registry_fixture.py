"""A store workspace with a synthetic model registry, served by ``vmn-exp ui``,
and a registry whose every store read waits an S3 round trip."""
import os
import threading
import time

from fastapi.testclient import TestClient

from vmn_exp.core.record_format import stamped
from vmn_exp.registry.log import set_alias
from vmn_exp.registry.names import HEADER_RECORD, version_record_name
from vmn_exp.registry.store import registry_storage
from vmn_exp.storage.areas import REGISTRY
from vmn_exp.storage.local import LocalSnapshotStorage

MODELS = "/api/v1/workspaces/st/models"
READS = ("list_apps", "list_files", "list_record_names", "load_file", "load_logs_by_writer")
T0 = "2026-01-01T00:00:00Z"


def store_storage(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    storage.save("app", "1.0.0-dev.a", {"verstr": "1.0.0-dev.a", "timestamp": T0}, {})
    return storage


def build_registry(storage, models, versions, aliased=0):
    """*models* models of *versions* versions each, written straight to their
    records; the first *aliased* models get a ``prod`` alias on their latest."""
    reg = registry_storage(storage)
    for m in range(models):
        name = f"m{m:03d}"
        reg.create_exclusive(name, HEADER_RECORD, stamped(
            {"model": name, "type": "model_header", "kind": "model", "timestamp": T0}), {})
        for n in range(1, versions + 1):
            reg.create_exclusive(name, version_record_name(n), stamped({
                "model": name, "n": n, "timestamp": f"2026-01-01T00:{n % 60:02d}:00Z",
                "run_ref": {"app": "app", "verstr": f"1.0.{n}"}, "artifact_path": "model.pkl",
            }), {})
        if m < aliased:
            set_alias(storage, name, "prod", versions)


def store_client(tmp_path, background):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("st", f"file://{os.path.abspath(tmp_path / 'store')}")
    app = create_app(manager, background_refresh=background)
    return app, TestClient(app)


class RegistryReads:
    """Counts the registry area's store reads, each delayed by *latency* s,
    and the peak of them in flight."""

    def __init__(self, latency):
        self.latency, self.calls, self.in_flight, self.peak = latency, [], 0, 0
        self._lock = threading.Lock()

    def wrap(self, name, real):
        def read(storage, *args, **kwargs):
            if storage.area != REGISTRY:
                return real(storage, *args, **kwargs)
            with self._lock:
                self.calls.append(name)
                self.in_flight += 1
                self.peak = max(self.peak, self.in_flight)
            try:
                time.sleep(self.latency)
                return real(storage, *args, **kwargs)
            finally:
                with self._lock:
                    self.in_flight -= 1
        return read


def registry_reads(monkeypatch, latency=0.0, names=READS):
    reads = RegistryReads(latency)
    for name in names:
        monkeypatch.setattr(LocalSnapshotStorage, name, reads.wrap(name, getattr(LocalSnapshotStorage, name)))
    return reads
