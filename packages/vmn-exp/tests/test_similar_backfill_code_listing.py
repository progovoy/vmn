"""``vmn-exp similar-backfill`` lists an app's code objects once, however
many exported-snapshot code verstrs its runs name: each one's code object is
picked from that one listing."""
import pytest
from backfill_helpers import (
    CODE,
    FILES,
    as_backfiller,
    features_entries,
    seed_code,
    seed_run,
)
from exp_helpers import _bootstrap, _exp, _storage
from vmn_exp.storage.areas import CODE as CODE_AREA
from vmn_exp.storage.local import LocalSnapshotStorage

CODE2 = "0.0.2-dev.abc1234.7654321"
KEY2 = CODE2 + ".7654321ffff"


@pytest.fixture
def store(app_layout, monkeypatch):
    _bootstrap(app_layout)
    as_backfiller(monkeypatch)
    return _storage(app_layout)


def _snapshot_run(storage, app, verstr, code_verstr):
    return seed_run(storage, app, verstr, from_snapshot=True, dirty_states=["pending"],
                    code_verstr=code_verstr, has_working_tree_patch=False,
                    has_local_commits_patch=False)


def test_runs_of_two_snapshot_code_verstrs_list_the_code_area_once(
        app_layout, store, capfd, monkeypatch):
    app = app_layout.app_name
    seed_code(store, app)
    seed_code(store, app, key=KEY2)
    _snapshot_run(store, app, CODE, CODE)
    _snapshot_run(store, app, CODE2, CODE2)
    listings = []
    real = LocalSnapshotStorage.list_record_names

    def counting(self, app_name):
        if self.area == CODE_AREA:
            listings.append(app_name)
        return real(self, app_name)

    monkeypatch.setattr(LocalSnapshotStorage, "list_record_names", counting)
    capfd.readouterr()

    assert _exp(app, action="similar-backfill") == 0

    assert capfd.readouterr().out.splitlines()[-1] == \
        "backfilled 2, partial 0, skipped 0, failed 0"
    assert listings == [app]
    for verstr in (CODE, CODE2):
        assert sorted(features_entries(store, app, verstr)[0]["changed"]["files"]) == FILES
