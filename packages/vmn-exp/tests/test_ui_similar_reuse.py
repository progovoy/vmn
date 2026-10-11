"""The UI's similar routes build an app's similar index once per lineage of
snapshots, off the request thread: a run-state rewrite (a heartbeat) moves the
app's index to a new generation without rebuilding the similar index, and a
request past the search deadline answers 503 while the build goes on."""
import os
import time

import pytest
import yaml
from similar_ui_fixture import TARGET, TWIN, client_for
from vmn_exp.core import similar_index
from vmn_exp.ui import routes_similar

pytest.importorskip("fastapi")

APP1 = "/api/v1/workspaces/ws1/apps/app1"
RUN_URL = f"{APP1}/experiments/{TARGET}/similar"


@pytest.fixture
def built(monkeypatch):
    calls, real = [], similar_index.build_profile

    def counted(row=None, *args, **kwargs):
        calls.append(row["verstr"])
        return real(row, *args, **kwargs)

    monkeypatch.setattr(similar_index, "build_profile", counted)
    return calls


def _rewrite_run_state(tmp_path, verstr, state, second):
    path = tmp_path / "ws1" / ".vmn" / "store" / "runs" / "app1" / verstr / "run_state.yml"
    path.write_text(yaml.dump(state))
    stamp = time.time() + second
    os.utime(path, (stamp, stamp))


def _status_of(response, verstr):
    assert response.status_code == 200, response.text
    return next(i["status"] for i in response.json()["items"] if i["verstr"] == verstr)


def test_a_run_state_rewrite_does_not_rebuild_the_similar_index(tmp_path, built):
    client = client_for(tmp_path, use_index=True)
    assert _status_of(client.get(RUN_URL), TWIN) == "succeeded"
    assert built  # the first request built it
    built.clear()
    for second, code in ((5, 3), (10, 0)):
        _rewrite_run_state(tmp_path, TWIN, {"state": "exited", "exit_code": code}, second)
        status = _status_of(client.get(RUN_URL), TWIN)
        assert status == ("failed" if code else "succeeded")  # a new generation answered
    assert built == []


def test_a_text_request_after_a_heartbeat_does_not_rebuild_either(tmp_path, built):
    client = client_for(tmp_path, use_index=True)
    assert client.get(f"{APP1}/similar", params={"text": "focal loss"}).status_code == 200
    built.clear()
    _rewrite_run_state(tmp_path, TWIN, {"state": "exited", "exit_code": 2}, 5)
    response = client.get(f"{APP1}/similar", params={"text": "focal loss"})
    assert _status_of(response, TWIN) == "failed"
    assert built == []


@pytest.mark.parametrize("use_index", [False, True], ids=["direct", "index"])
def test_a_search_past_its_deadline_is_503_and_the_build_goes_on(tmp_path, built, monkeypatch,
                                                                use_index):
    client = client_for(tmp_path, use_index=use_index)
    monkeypatch.setattr(routes_similar, "SEARCH_DEADLINE_SEC", 0.0)
    for url, params in ((RUN_URL, {}), (f"{APP1}/similar", {"text": "focal loss"})):
        response = client.get(url, params=params)
        assert response.status_code == 503, response.text
        assert "retry" in response.json()["detail"].lower()
        assert response.headers.get("retry-after")
    monkeypatch.setattr(routes_similar, "SEARCH_DEADLINE_SEC", 10.0)
    assert client.get(RUN_URL).status_code == 200
