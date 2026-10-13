"""``vmn-exp list`` shows an incomplete sweep as such (plan 20 A7/D12): a grid
of 3 with 2 finished trials reads ``created (2/3 incomplete)``, and once every
trial ran the outer reads ``created/succeeded``."""
import pytest
from exp_helpers import _storage
from test_sweep_cli import _create, _vmn_exp
from vmn_exp.sdk.reader import list_runs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SWEEP_PARAMS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FAIL_DIR", str(tmp_path))


def _outer_line(app_layout, sweep, capsys):
    capsys.readouterr()
    assert _vmn_exp("list", app_layout.app_name) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if f"] {sweep} " in ln]
    assert len(lines) == 1, lines
    return lines[0]


def test_list_shows_an_incomplete_sweep_then_a_succeeded_one(app_layout, tmp_path, capsys):
    sweep = _create(app_layout, tmp_path, capsys)
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep, "--count", "2") == 0
    assert "created (2/3 incomplete)" in _outer_line(app_layout, sweep, capsys)
    rows = list_runs(app_layout.app_name, storage=_storage(app_layout),
                     query='tree_status = "created"', use_index=False)
    assert sweep in [r["verstr"] for r in rows]

    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0
    line = _outer_line(app_layout, sweep, capsys)
    assert "created/succeeded" in line
    assert "incomplete" not in line
