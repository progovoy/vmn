"""Plan 25 §2: a similar search over the persisted index is as fresh as a
refresh — a run edited in place since the index was last saved is searched
as it now is, not only runs created or removed since."""
import pytest
from similar_seed import WRITER, seed, verstr
from vmn_exp.core import index as experiment_index
from vmn_exp.core.similar_search import find
from vmn_exp.snapshot import open_storage

APP = "trainer"


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / "store")


def _fresh(root, monkeypatch):
    """A new process's storage over the same store and index."""
    monkeypatch.setattr(experiment_index, "_SHARED", {})
    return open_storage(root=root, area="runs")


def _found(storage, text):
    return [item["verstr"] for item in find(storage, APP, None, text_only=True, context=text)]


def test_a_search_sees_an_intent_edited_since_the_index_was_saved(root, monkeypatch):
    storage = open_storage(root=root, area="runs")
    a = seed(storage, APP, verstr(1), intent={"text": "focal loss for imbalance"})
    seed(storage, APP, verstr(2), intent={"text": "label smoothing"})
    assert _found(storage, "focal loss") == [a]  # indexes the app
    storage.append_log_entry(APP, a, WRITER, {"type": "intent", "text": "mixup augmentation",
                                              "timestamp": "2026-01-02T00:00:00Z",
                                              "source": "user"})
    assert _found(_fresh(root, monkeypatch), "mixup augmentation") == [a]
