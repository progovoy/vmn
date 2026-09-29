"""vmn_exp.sdk.reader.param_importance: importance over an app's filtered runs."""
import pytest

from vmn_exp.core.query import QueryError
from vmn_exp.sdk.reader import param_importance
from vmn_exp.storage.open import get_snapshot_storage

APP = "app"


def _storage(tmp_path):
    return get_snapshot_storage("local", vmn_root_path=str(tmp_path), subdir="experiments")


def _run(storage, i, loss, **params):
    verstr = f"1.0.0-dev.r{i:04d}"
    ts = f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": ts}, {})
    storage.append_log_entry(APP, verstr, "w", {"timestamp": ts, "type": "create", "params": params})
    storage.append_log_entry(
        APP, verstr, "w", {"timestamp": ts, "type": "metrics", "values": {"loss": loss}}
    )


@pytest.fixture
def seeded(tmp_path):
    storage = _storage(tmp_path)
    for i in range(60):
        lr = (i * 7 % 60) / 60
        _run(storage, i, loss=2 * lr + (i % 2) * 0.01, lr=lr, seed=i % 5, model="a" if i < 30 else "b")
    return storage


def test_the_driving_param_ranks_first(seeded):
    result = param_importance(APP, "loss", storage=seeded)
    assert result[0]["param"] == "lr"
    assert {entry["param"] for entry in result} == {"lr", "seed", "model"}
    assert result[0]["n"] == 60


def test_the_query_narrows_the_runs(seeded):
    result = param_importance(APP, "loss", storage=seeded, query='params.model = "a"')
    assert {entry["param"] for entry in result} == {"lr", "seed"}  # model is single-valued
    assert result[0]["n"] == 30


def test_an_unknown_metric_or_bad_query_raises(seeded):
    with pytest.raises(ValueError, match="nope"):
        param_importance(APP, "nope", storage=seeded)
    with pytest.raises(QueryError):
        param_importance(APP, "loss", storage=seeded, query="metrics.loss <")
