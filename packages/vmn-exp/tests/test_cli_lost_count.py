"""Plan 34 §3 in the CLI: ``vmn-exp list`` and ``show`` print an outer run's
lost runs (stuck under it once it ended) beside its tree status, as the board
does: ``succeeded · 1 lost``. A tree with none prints no count."""
from exp_helpers import _exp
from similar_seed import seed, verstr
from test_query_below_entry_points import _stuck

from exp_helpers import _bootstrap, _storage


def _seed(app_layout):
    """1 ended -> 2 succeeded, 3 lost, 4 lost; 5 ended -> 6 succeeded."""
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    for n, parent, code in ((1, None, 0), (2, 1, 0), (3, 1, None), (4, 1, None),
                            (5, None, 0), (6, 5, 0)):
        seed(storage, app, verstr(n), parent=parent and verstr(parent), exit_code=code)
    for n in (3, 4):
        _stuck(app_layout, storage, app, verstr(n))
    return app


def _out(capfd, app, **kwargs):
    capfd.readouterr()
    code = _exp(app, **kwargs)
    out = capfd.readouterr()
    assert code == 0, out.err
    return out.out


def _line(out, n):
    (line,) = [line for line in out.splitlines() if f"] {verstr(n)}" in line]
    return line


def test_list_prints_an_outer_runs_lost_runs(app_layout, capfd):
    app = _seed(app_layout)
    out = _out(capfd, app, action="list")
    assert "succeeded · 2 lost" in _line(out, 1)
    assert "lost" not in _line(out, 5)


def test_a_queried_list_counts_them_too(app_layout, capfd):
    app = _seed(app_layout)
    out = _out(capfd, app, action="list", extra_args=["--query", "depth = 0"])
    assert "succeeded · 2 lost" in _line(out, 1)


def test_show_prints_an_outer_runs_lost_runs(app_layout, capfd):
    app = _seed(app_layout)
    assert "Subtree:   succeeded · 2 lost" in _out(capfd, app, action="show", version=verstr(1))
    assert "lost" not in _out(capfd, app, action="show", version=verstr(5))
