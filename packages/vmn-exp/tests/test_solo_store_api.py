"""End to end over a fresh local store (plan 43 F13): a dozen SDK runs, each
logging one metric, are what a standalone ``vmn-exp ui`` serves to the runs
board, with no token: the facets count no outer runs and the ``top=singles``
page lists every run with its metric."""
import pytest
from exp_helpers import _bootstrap
from run_code_seed import client

pytest.importorskip("fastapi")

from vmn_exp.sdk import start_run  # noqa: E402

RUNS = 12


def _base(app_layout):
    return f"/api/v1/workspaces/main/apps/{app_layout.app_name}"


def test_twelve_sdk_runs_in_a_fresh_local_store_are_all_on_the_runs_board_without_a_token(
        app_layout):
    _bootstrap(app_layout)
    ids = set()
    for i in range(RUNS):
        with start_run(app_layout.app_name) as run:
            run.log_metrics({"loss": 1.0 / (i + 1)}, step=0)
            ids.add(run.id)
    served = client(app_layout)

    facets = served.get(f"{_base(app_layout)}/experiments-facets")
    page = served.get(f"{_base(app_layout)}/experiments", params={"top": "singles", "limit": 50})

    assert facets.status_code == 200 and page.status_code == 200
    assert (facets.json()["jobs"], facets.json()["singles"]) == (0, RUNS)
    body = page.json()
    assert "indexing" not in body
    assert body["total"] == RUNS
    assert {row["verstr"] for row in body["rows"]} == ids
    assert all("loss" in row["metrics"] for row in body["rows"])
