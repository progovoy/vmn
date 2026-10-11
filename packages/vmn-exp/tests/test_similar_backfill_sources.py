"""Where ``vmn-exp similar-backfill`` finds a run's code: its code object
(``code:``), the one code object of an exported snapshot's code verstr, the
record itself (patches from before the code store) — or nowhere, for a clean
tree (complete) or a code object that is gone (partial)."""
import pytest
from backfill_helpers import (
    CODE,
    CREATOR,
    FILES,
    KEY,
    LC,
    WT,
    as_backfiller,
    dirty_run,
    features_entries,
    seed_code,
    seed_run,
)
from exp_helpers import _bootstrap, _exp, _storage
from vmn_exp.cli import similar_backfill

V1 = CODE
V2 = CODE + ".r2"
DEP_WT = """diff --git a/lib/data.py b/lib/data.py
--- a/lib/data.py
+++ b/lib/data.py
@@ -3,2 +3,3 @@ def load(path):
+    pass
"""


@pytest.fixture
def store(app_layout, monkeypatch):
    _bootstrap(app_layout)
    as_backfiller(monkeypatch)
    return _storage(app_layout)


def _backfill(app_layout, capfd):
    capfd.readouterr()
    code = _exp(app_layout.app_name, action="similar-backfill")
    return code, capfd.readouterr().out.splitlines()


def _snapshot_run(storage, app, verstr, dirty_states):
    """A run ``vmn-exp create --from-snapshot`` recorded: no ``code`` key,
    its code verstr the exported run's."""
    return seed_run(storage, app, verstr, from_snapshot=True, dirty_states=dirty_states,
                    has_working_tree_patch=False, has_local_commits_patch=False)


def test_a_clean_tree_run_gets_a_complete_entry_with_no_changes(app_layout, store, capfd):
    app = app_layout.app_name
    seed_run(store, app, V1, dirty_states=[])

    code, lines = _backfill(app_layout, capfd)

    assert code == 0
    assert f"{V1}  backfilled (clean tree)" in lines
    [entry] = features_entries(store, app, V1)
    assert "changed" not in entry and "commits" not in entry
    assert entry["author"] == {"writer": CREATOR}


def test_a_run_whose_code_object_is_gone_is_partial(app_layout, store, capfd):
    app = app_layout.app_name
    dirty_run(store, app, V1)

    code, lines = _backfill(app_layout, capfd)

    assert code == 0
    assert f"{V1}  partial (code object {KEY} is missing)" in lines
    assert lines[-1] == "backfilled 0, partial 1, skipped 0, failed 0"
    [entry] = features_entries(store, app, V1)
    assert entry["source"] == "backfill" and "changed" not in entry
    assert entry["author"] == {"writer": CREATOR}
    assert _backfill(app_layout, capfd)[1][-1] == "backfilled 0, partial 0, skipped 1, failed 0"


def test_snapshot_runs_find_their_code_object_by_code_verstr_once(
        app_layout, store, capfd, monkeypatch):
    app = app_layout.app_name
    seed_code(store, app)
    _snapshot_run(store, app, V1, ["pending"])
    _snapshot_run(store, app, V2, ["outgoing"])
    lookups = []
    real = similar_backfill.find_code_key
    monkeypatch.setattr(similar_backfill, "find_code_key",
                        lambda *a: lookups.append(a[2]) or real(*a))

    code, lines = _backfill(app_layout, capfd)

    assert code == 0 and lookups == [CODE]
    assert lines[-1] == "backfilled 2, partial 0, skipped 0, failed 0"
    for verstr in (V1, V2):
        assert sorted(features_entries(store, app, verstr)[0]["changed"]["files"]) == FILES


def test_a_dirty_snapshot_run_without_its_code_object_is_partial(app_layout, store, capfd):
    app = app_layout.app_name
    _snapshot_run(store, app, V1, ["pending"])
    _snapshot_run(store, app, V2, [])

    code, lines = _backfill(app_layout, capfd)

    assert code == 0
    assert f"{V1}  partial (no code object of {CODE} in the store)" in lines
    assert f"{V2}  backfilled (clean tree)" in lines


def test_patches_from_before_the_code_store_are_read_from_the_record(
        app_layout, store, capfd):
    app = app_layout.app_name
    store.save(app, V1, {"verstr": V1, "timestamp": "2026-01-01T00:00:00Z",
                         "base_commit": "abc1234", "diff_hash": "1234567ffff",
                         "has_working_tree_patch": True, "has_local_commits_patch": True},
               {"working_tree": WT, "local_commits": LC, "untracked_files": b"TAR"})
    store.append_log_entry(app, V1, CREATOR, {"timestamp": "2026-01-01T00:00:01Z",
                                              "type": "create"})

    assert _backfill(app_layout, capfd)[0] == 0

    [entry] = features_entries(store, app, V1)
    assert sorted(entry["changed"]["files"]) == FILES
    assert entry["author"]["git_user_email"] == "alice@x.io"


def test_a_deps_patches_count_under_the_deps_path(app_layout, store, capfd):
    app = app_layout.app_name
    seed_code(store, app, payload={"working_tree": WT,
                                   "deps": {"../libs/data": {"working_tree": DEP_WT}}})
    dirty_run(store, app, V1, dep_base_commits={"../libs/data": "fff0000"},
              changesets={".": {"hash": "abc1234"}, "../libs/data": {"hash": "fff0000"}})

    assert _backfill(app_layout, capfd)[0] == 0

    [entry] = features_entries(store, app, V1)
    assert sorted(entry["changed"]["files"]) == ["../libs/data/lib/data.py", "src/loss.py"]
    assert "../libs/data/lib/data.py::load" in entry["changed"]["symbols"]
