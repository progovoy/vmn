"""A storage without store areas (a duck-typed or third-party backend that only
implements the documented SnapshotStorage methods) has no app settings: reads
answer "none" instead of raising."""
from vmn_exp.core import app_settings_store as store
from vmn_exp.storage.base import SnapshotStorage


class _DuckStorage:
    """No ``in_area`` at all."""


class _AreaLessStorage(SnapshotStorage):
    """Implements the abstract methods only: ``in_area`` raises."""

    def save(self, *a, **k): ...
    def load_record(self, *a, **k): return None, None
    def list_snapshots(self, *a, **k): return []
    def update_note(self, *a, **k): ...
    def delete(self, *a, **k): ...
    def load_file(self, *a, **k): return None
    def save_file(self, *a, **k): ...
    def save_artifact_file(self, *a, **k): ...
    def local_record_dir(self, *a, **k): return None


def test_duck_typed_storage_reads_no_settings():
    storage = _DuckStorage()
    assert store.read_settings_text(storage, "app") is None
    assert store.read_settings(storage, "app") == {}
    assert store.settings_metadata(storage, "app") == {}
    assert store.app_metrics_schema(storage, "app", {"loss": {"goal": "min"}}) == {
        "loss": {"goal": "min"}
    }


def test_area_less_backend_reads_no_settings():
    storage = _AreaLessStorage()
    assert store.read_settings_text(storage, "app") is None
    assert store.settings_metadata(storage, "app") == {}
