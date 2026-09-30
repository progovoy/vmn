"""``vmn-exp importance <app> --metric m``: which params drive a metric."""
import json

from exp_helpers import _bootstrap, _exp, _storage


def _seed(app_layout):
    storage = _storage(app_layout)
    app = app_layout.app_name
    for i in range(40):
        verstr = f"0.0.1-dev.r{i:04d}"
        ts = f"2026-01-01T00:00:{i:02d}Z"
        lr = (i * 7 % 40) / 40
        storage.save(app, verstr, {"verstr": verstr, "timestamp": ts}, {})
        storage.append_log_entry(app, verstr, "w", {
            "timestamp": ts, "type": "create",
            "params": {"lr": lr, "seed": i % 4, "model": "a" if i < 20 else "b"},
        })
        storage.append_log_entry(app, verstr, "w", {
            "timestamp": ts, "type": "metrics", "values": {"loss": 2 * lr + (i % 2) * 0.01},
        })


def _importance(capfd, app_layout, *extra):
    capfd.readouterr()
    code = _exp(app_layout.app_name, action="importance", extra_args=list(extra))
    return code, capfd.readouterr()


def test_json_lists_params_most_important_first(app_layout, capfd):
    _bootstrap(app_layout)
    _seed(app_layout)
    code, out = _importance(capfd, app_layout, "--metric", "loss", "--json")
    assert code == 0, out.err
    body = json.loads(out.out)
    assert body[0]["param"] == "lr"
    assert {entry["param"] for entry in body} == {"lr", "seed", "model"}


def test_query_narrows_and_the_table_names_each_param(app_layout, capfd):
    _bootstrap(app_layout)
    _seed(app_layout)
    code, out = _importance(capfd, app_layout, "--metric", "loss", "--query", 'params.model = "a"')
    assert code == 0, out.err
    lines = out.out.splitlines()
    assert lines[0].split()[:2] == ["param", "importance"]
    assert lines[1].split()[0] == "lr"
    assert not any(line.split()[0] == "model" for line in lines[1:])


def test_unknown_metric_or_missing_flag_fails(app_layout, capfd):
    _bootstrap(app_layout)
    _seed(app_layout)
    code, out = _importance(capfd, app_layout, "--metric", "nope")
    assert code == 1
    assert "nope" in out.err + out.out
    code, _ = _importance(capfd, app_layout)
    assert code == 1
    code, _ = _importance(capfd, app_layout, "--metric", "loss", "--query", "metrics.loss <")
    assert code == 1
