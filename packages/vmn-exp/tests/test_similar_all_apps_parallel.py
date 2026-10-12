"""``similar --all-apps`` brings the other apps' indexes up to date side by
side, and still searches them in the store's app order."""
import threading

import pytest
from similar_seed import TRAIN_STEP, features, seed, verstr
from vmn_exp.core import similar_search
from vmn_exp.snapshot import open_storage

CHANGES = features(["train.py"], [TRAIN_STEP])


@pytest.fixture
def storage(tmp_path):
    return open_storage(root=str(tmp_path / "store"), area="runs")


def test_other_apps_are_refreshed_side_by_side_in_app_order(storage, monkeypatch):
    target = seed(storage, "trainer", verstr(1), changes=CHANGES)
    for n, app in enumerate(("alpha", "beta"), 2):
        seed(storage, app, verstr(n), changes=CHANGES)
    both_refreshing = threading.Barrier(2, timeout=5)
    real = similar_search.app_snapshot

    def refresh(store, app, schema=None):
        if app != "trainer":
            both_refreshing.wait()  # breaks unless the other app refreshes meanwhile
        return real(store, app, schema)

    monkeypatch.setattr(similar_search, "app_snapshot", refresh)

    scopes = similar_search._other_scopes(storage, "trainer", None)

    assert [app for app, _, _ in scopes] == [a for a in storage.list_apps() if a != "trainer"]
    assert [snap.app_name for _, snap, _ in scopes] == [app for app, _, _ in scopes]
    found = similar_search.find(storage, "trainer", target, {}, all_apps=True)
    assert {item["app"] for item in found} == {"alpha", "beta"}
