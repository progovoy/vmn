"""``GET .../experiments/{verstr}/patch?max_bytes=`` (plan 20 K2): what
``vmn-exp show --patch --json`` prints as ``patch``, plus the changed files
parsed from the text, with an ETag on the run's code identity."""
import pytest
from exp_helpers import _bootstrap, _exp, extract_dev_verstr
from run_code_seed import client, run_url, seed_run
from test_exp_show_patch_cli import _dirty_run, _show_json
from version_stamp.core import logging as vmn_logging

pytest.importorskip("fastapi")


@pytest.fixture(autouse=True)
def _logger():
    vmn_logging.ensure_logger()


def _patch(app_layout, verstr, **params):
    return client(app_layout).get(run_url(app_layout, verstr, "/patch"), params=params)


def test_a_dirty_run_serves_its_patch_text_and_files(app_layout, capfd):
    verstr = _dirty_run(app_layout, capfd)
    resp = _patch(app_layout, verstr)
    assert resp.status_code == 200
    body = resp.json()
    cli = _show_json(capfd, app_layout, verstr, "--patch")["patch"]
    assert body["text"] == cli["text"]
    assert body["truncated"] is False
    assert {"path": "tracked.txt", "added": 1, "removed": 1} in body["files"]
    assert {"path": "loss.py", "added": 2, "removed": 0} in body["files"]


def test_max_bytes_caps_the_text(app_layout, capfd):
    verstr = _dirty_run(app_layout, capfd)
    body = _patch(app_layout, verstr, max_bytes=40).json()
    assert body["truncated"] is True
    assert len(body["text"].encode()) <= 40


def test_a_clean_run_has_no_code(app_layout, capfd):
    _bootstrap(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    body = _patch(app_layout, verstr).json()
    assert body == {"text": None, "reason": "no_code", "files": []}


def test_the_etag_repeats_and_answers_304(app_layout, capfd):
    verstr = _dirty_run(app_layout, capfd)
    api = client(app_layout)
    url = run_url(app_layout, verstr, "/patch")
    first, second = api.get(url), api.get(url)
    assert first.headers["etag"] == second.headers["etag"]
    again = api.get(url, headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    capped = api.get(url, params={"max_bytes": 40})
    assert capped.headers["etag"] != first.headers["etag"]


def test_an_unknown_run_is_404(app_layout):
    seed_run(app_layout, "0.0.1-dev.r1", 1)
    assert _patch(app_layout, "0.0.1-dev.nope").status_code == 404


def test_max_bytes_must_be_positive(app_layout):
    seed_run(app_layout, "0.0.1-dev.r1", 1)
    assert _patch(app_layout, "0.0.1-dev.r1", max_bytes=0).status_code == 400
