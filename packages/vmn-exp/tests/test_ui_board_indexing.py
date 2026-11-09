"""While the app's index snapshot is still loading (a cold load, an upgrade's
re-derive), every board answer built from it says so, ``indexing {loaded,
total}`` like experiments-status, instead of a silent partial (or empty) board
(plan 33 §2.2). Its ETag follows the load, so no client keeps a loading
answer once the load moved on or ended."""
import dataclasses

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.local import LocalSnapshotStorage  # noqa: E402
from vmn_exp.ui.experiment_source import ExperimentSource  # noqa: E402

APP = "app"
PARENT, CHILD = "1.0.0-dev.a", "1.0.0-dev.b"
BASE = f"/api/v1/workspaces/st/apps/{APP}"
ANSWERS = [
    f"{BASE}/experiments?limit=50",
    f"{BASE}/experiments?top=jobs&limit=50",
    f"{BASE}/experiments?top=singles&limit=50",
    f"{BASE}/experiments?group=status",
    f"{BASE}/experiments?top=jobs&group=status",
    f"{BASE}/experiments?children_of={PARENT}",
    f"{BASE}/experiments-columns",
    f"{BASE}/experiments-facets",
    f"{BASE}/experiments-pivot?rows=status&cols=status",
]


class _Loading:
    """Serves the app's real snapshots as if their index were *state* far
    into its load (None: loaded), one copy per snapshot and state."""

    def __init__(self, monkeypatch):
        self.state, self._copies = None, {}
        real = ExperimentSource.snapshot

        def snapshot(source, *args, **kwargs):
            snap = real(source, *args, **kwargs)
            if self.state is None:
                return snap
            key = (id(snap), self.state)
            if key not in self._copies:
                self._copies[key] = (snap, dataclasses.replace(snap, loading=self.state))
            return self._copies[key][1]

        monkeypatch.setattr(ExperimentSource, "snapshot", snapshot)


@pytest.fixture
def board(tmp_path, monkeypatch):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    storage.save(APP, PARENT, {"verstr": PARENT, "timestamp": "2026-01-01T00:00:00Z"}, {})
    storage.save(APP, CHILD, {"verstr": CHILD, "timestamp": "2026-01-01T00:00:01Z",
                              "parent": PARENT}, {})
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("st", f"file://{tmp_path / 'store'}")
    loading = _Loading(monkeypatch)
    return TestClient(create_app(manager)), loading


@pytest.mark.parametrize("url", ANSWERS)
def test_a_board_answer_says_the_index_is_still_loading(board, url):
    client, loading = board
    loading.state = (2, 734_000)
    answer = client.get(url)
    assert answer.status_code == 200, answer.text
    assert answer.json()["indexing"] == {"loaded": 2, "total": 734_000}


@pytest.mark.parametrize("url", ANSWERS)
def test_a_loaded_index_answers_without_indexing(board, url):
    client, _ = board
    answer = client.get(url)
    assert answer.status_code == 200, answer.text
    assert "indexing" not in answer.json()


def test_a_listing_without_a_known_total_still_says_it_is_loading(board):
    client, loading = board
    loading.state = (2, None)
    assert client.get(ANSWERS[0]).json()["indexing"] == {"loaded": 2, "total": None}


@pytest.mark.parametrize("url", ANSWERS)
def test_the_etag_moves_with_the_load_and_when_it_ends(board, url):
    client, loading = board
    loading.state = (1, 10)
    first = client.get(url)
    loading.state = (5, 10)
    later = client.get(url, headers={"If-None-Match": first.headers["etag"]})
    loading.state = None
    done = client.get(url, headers={"If-None-Match": later.headers["etag"]})

    assert later.status_code == 200 and later.json()["indexing"]["loaded"] == 5
    assert done.status_code == 200 and "indexing" not in done.json()
