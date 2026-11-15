"""The storage contract: ``create_exclusive`` has no default, and the
conformance kit (``vmn_exp.storage.conformance``) a plugin author runs
against their backend."""
import pytest

from memory_storage import CheckThenSaveStorage, MemoryStorage
from vmn_exp.storage import conformance
from vmn_exp.storage.base import SnapshotStorage


def test_a_subclass_without_create_exclusive_cannot_be_instantiated():
    class NoClaim(SnapshotStorage):
        """Every other abstract method, as the documented contract lists them."""

        def save(self, *a, **k): ...
        def load_record(self, *a, **k): return None, None
        def list_snapshots(self, *a, **k): return []
        def update_note(self, *a, **k): ...
        def delete(self, *a, **k): ...
        def load_file(self, *a, **k): return None
        def save_file(self, *a, **k): ...
        def save_artifact_file(self, *a, **k): ...
        def local_record_dir(self, *a, **k): return None

    with pytest.raises(TypeError, match="create_exclusive"):
        NoClaim()


def test_kit_passes_an_atomic_in_memory_store():
    results = conformance.check_store(MemoryStorage)

    assert [(name, error) for name, error in results if error is not None] == []


def test_kit_fails_the_race_check_for_a_check_then_save_store():
    results = dict(conformance.check_store(lambda: CheckThenSaveStorage(conformance.RACERS)))

    assert isinstance(results.pop("check_racing_claims_get_exactly_one_win"), AssertionError)
    assert results == {name: None for name in results}


def test_kit_reports_every_check_by_name():
    names = [name for name, _ in conformance.check_store(MemoryStorage)]

    assert names == [check.__name__ for check in conformance.CHECKS]
    assert len(set(names)) == len(names) >= 8


def test_kit_reports_a_raising_check_as_its_error():
    class NoFiles(MemoryStorage):
        def load_file(self, app_name, verstr, filename):
            raise NotImplementedError("no files here")

    results = dict(conformance.check_store(NoFiles))

    assert isinstance(results["check_file_round_trip"], NotImplementedError)
