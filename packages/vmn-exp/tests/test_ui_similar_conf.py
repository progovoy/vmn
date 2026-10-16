"""The similar-runs UI routes score with the app's conf
``experiment.similar.weights``, like ``vmn-exp similar`` and the SDK reader,
re-read when the conf changes."""
import os

import pytest
import yaml
from similar_ui_fixture import OTHER, TARGET, TWIN, client_for
from vmn_exp.core.app_conf import read_experiment_conf
from vmn_exp.core.similar_search import find
from vmn_exp.core.similar_weights import SIGNALS
from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root

pytest.importorskip("fastapi")

APP1 = "/api/v1/workspaces/ws1/apps/app1"
# Every signal off but the branch, which the target, its twin and the
# unrelated run share: only they match, and bm25 ranks the unrelated run's
# shorter document first.
BRANCH_ONLY = dict(dict.fromkeys(SIGNALS, 0), branch=1)


@pytest.fixture(params=[False, True], ids=["direct", "index"])
def client(request, tmp_path):
    return client_for(tmp_path, use_index=request.param)


def _write_weights(root, weights):
    path = os.path.join(root, ".vmn", "app1", "conf.yml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump({"conf": {"experiment": {"similar": {"weights": weights}}}}, f)


def _items(response):
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _ranked(items):
    return [(item["verstr"], item["score"]) for item in items]


def test_conf_weights_change_the_ranking_of_a_runs_similar_runs(client, tmp_path):
    assert _items(client.get(f"{APP1}/experiments/{TARGET}/similar"))[0]["verstr"] == TWIN

    _write_weights(str(tmp_path / "ws1"), BRANCH_ONLY)

    items = _items(client.get(f"{APP1}/experiments/{TARGET}/similar"))
    assert [item["verstr"] for item in items] == [OTHER, TWIN]
    assert items[0]["score"] == 1.0


def test_the_ui_ranks_like_the_cli_and_sdk_under_the_same_conf(client, tmp_path):
    root = str(tmp_path / "ws1")
    _write_weights(root, BRANCH_ONLY)
    storage = open_storage(root=local_store_root(root), area="runs")

    expected = find(storage, "app1", TARGET, read_experiment_conf("app1", root))

    items = _items(client.get(f"{APP1}/experiments/{TARGET}/similar"))
    assert _ranked(items) == _ranked(expected)
    default = find(storage, "app1", TARGET, {})
    assert _ranked(items) != _ranked(default)
