"""Plan 14 store areas: every area under ``<root>/<area>/<app-key>/<name>``."""
import os

import boto3

from s3_helpers import BUCKET, mocked_bucket
from vmn_exp.storage import areas
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.registry import open_store

VERSTR = "1.0.0-dev.abc1234"


def _keys():
    listed = boto3.client("s3").list_objects_v2(Bucket=BUCKET).get("Contents", [])
    return sorted(o["Key"] for o in listed)


def test_runs_and_snapshots_of_one_tree_never_share_a_key(monkeypatch):
    with mocked_bucket(monkeypatch):
        uri = f"s3://{BUCKET}/team"
        runs = open_store(uri, area=areas.RUNS)
        snaps = open_store(uri, area=areas.SNAPSHOTS)
        assert snaps.create_exclusive("my_app", VERSTR, {"verstr": VERSTR}, {})
        assert runs.create_exclusive("my_app", VERSTR, {"verstr": VERSTR}, {})
        keys = [k for k in _keys() if k.endswith("metadata.yml")]
        assert keys == [
            f"team/runs/my_app/{VERSTR}/metadata.yml",
            f"team/snapshots/my_app/{VERSTR}/metadata.yml",
        ]
        assert runs.list_verstrs("my_app") == [VERSTR]
        assert snaps.list_verstrs("my_app") == [VERSTR]


def test_uri_without_path_uses_the_vmn_root(monkeypatch):
    with mocked_bucket(monkeypatch):
        store = open_store(f"s3://{BUCKET}", area=areas.CODE)
        store.save("root/svc", "k", {"verstr": "k"}, {})
        assert "vmn/code/root-svc/k/metadata.yml" in _keys()


def test_local_root_layout_tag_form_and_one_gitignore(tmp_path):
    root = str(tmp_path / "store")
    storage = LocalSnapshotStorage(root, areas.RUNS)
    storage.save("root_app/svc", VERSTR, {"verstr": VERSTR}, {})
    record = os.path.join(root, "runs", "root_app-svc", VERSTR, "metadata.yml")
    assert os.path.isfile(record)
    with open(os.path.join(root, ".gitignore")) as f:
        assert f.read() == "*\n"
    assert not os.path.exists(os.path.join(root, "runs", "root_app-svc", ".gitignore"))
    assert storage.list_apps() == ["root_app/svc"]


def test_file_uri_root_is_the_dir(tmp_path):
    store = open_store(f"file://{tmp_path}", area=areas.SNAPSHOTS)
    store.save("app", VERSTR, {"verstr": VERSTR}, {})
    assert os.path.isfile(tmp_path / "snapshots" / "app" / VERSTR / "metadata.yml")


def test_in_area_reaches_a_sibling_area(tmp_path):
    storage = open_storage(None, str(tmp_path), area=areas.RUNS)
    storage.in_area(areas.CODE).save("app", "k", {"verstr": "k"}, {})
    assert os.path.isfile(tmp_path / "code" / "app" / "k" / "metadata.yml")
    assert storage.list_apps() == []


def test_object_store_in_area(monkeypatch):
    with mocked_bucket(monkeypatch):
        runs = open_store(f"s3://{BUCKET}/team", area=areas.RUNS)
        runs.in_area(areas.SWEEPS).save("a~s", "t0", {"verstr": "t0"}, {})
        assert "team/sweeps/a~s/t0/metadata.yml" in _keys()


def test_repo_local_root(tmp_path):
    from vmn_exp.storage.areas import local_store_root

    assert local_store_root(str(tmp_path)) == os.path.join(str(tmp_path), ".vmn", "store")
