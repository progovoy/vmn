"""Local snapshot stores use the v2 layout under ``.vmn/store/``."""
import os

import pytest

from version_stamp.snapshot.code_store import code_app
from version_stamp.snapshot.stores import local_snapshot_stores


@pytest.mark.parametrize("app,key", [("app", "app"), ("root/svc", "root-svc")])
def test_records_and_code_use_store_layout(tmp_path, app, key):
    stores = local_snapshot_stores(str(tmp_path))
    stores.records.save(app, "0.0.1-dev.abc", {"verstr": "0.0.1-dev.abc"}, {})
    stores.code.save(code_app(app), "0.0.1-dev.abc.ff", {"verstr": "k"}, {})
    store = tmp_path / ".vmn" / "store"
    assert (store / "snapshots" / key / "0.0.1-dev.abc" / "metadata.yml").is_file()
    assert (store / "code" / key / "0.0.1-dev.abc.ff" / "metadata.yml").is_file()
    assert (store / ".gitignore").read_text() == "*\n"
    assert not os.path.exists(store / "snapshots" / key / ".gitignore")
    assert stores.records.load(app, "0.0.1-dev.abc")[0]["verstr"] == "0.0.1-dev.abc"


def test_runs_are_scanned_from_experiments_dir(tmp_path):
    stores = local_snapshot_stores(str(tmp_path))
    stores.runs.save("root/svc", "0.0.1-dev.run", {"verstr": "r", "code": "k"}, {})
    assert (tmp_path / ".vmn/store/experiments/root-svc/0.0.1-dev.run").is_dir()
