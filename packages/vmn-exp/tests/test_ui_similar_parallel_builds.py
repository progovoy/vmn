"""An all-apps similar request starts every app's index build before it
waits on any: the builds run side by side under the request's one deadline."""
import threading

import pytest
from similar_ui_fixture import TARGET, client_for
from vmn_exp.core import similar_cache

pytest.importorskip("fastapi")

RUN_URL = f"/api/v1/workspaces/ws1/apps/app1/experiments/{TARGET}/similar"


def test_an_all_apps_request_builds_the_apps_indexes_side_by_side(tmp_path, monkeypatch):
    client = client_for(tmp_path, use_index=True)
    both_building = threading.Barrier(2, timeout=5)
    real = similar_cache.build_index

    def build(*args, **kwargs):
        both_building.wait()  # breaks unless the other app's build runs meanwhile
        return real(*args, **kwargs)

    monkeypatch.setattr(similar_cache, "build_index", build)

    response = client.get(RUN_URL, params={"all_apps": 1})

    assert response.status_code == 200, response.text
    assert {item["app"] for item in response.json()["items"]} >= {"app1", "app2"}
