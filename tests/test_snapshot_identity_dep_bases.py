"""Dep base commits are part of a snapshot's identity (``same_state``), without
churning the verstrs of old records or of deps sitting at their stamp commit."""
from version_stamp.snapshot.identity import _unique_snapshot_verstr, same_state
from version_stamp.snapshot.local_store import LocalRecordStore

APP = "my_app"
BASE, COMMIT = "0.0.1", "abcdef1234567"
DIFF_HASH = "1234567" + "a" * 57
SHORT = f"{BASE}-dev.abcdef1.1234567"
CHANGESETS = {".": {"hash": "aaa"}, "../dep": {"hash": "bbb"}}
AT_STAMP = {"../dep": "bbb"}
MOVED = {"../dep": "ccc"}


def _meta(dep_bases=None):
    meta = {"verstr": SHORT, "diff_hash": DIFF_HASH, "changesets": CHANGESETS}
    if dep_bases is not None:
        meta["dep_base_commits"] = dep_bases
    return meta


def test_records_with_other_dep_bases_are_different_states():
    assert same_state(_meta(MOVED), DIFF_HASH, CHANGESETS, MOVED)
    assert not same_state(_meta(MOVED), DIFF_HASH, CHANGESETS, AT_STAMP)
    assert not same_state(_meta(AT_STAMP), DIFF_HASH, CHANGESETS, MOVED)


def test_a_dep_base_at_its_changeset_hash_equals_no_recorded_base():
    assert same_state(_meta({}), DIFF_HASH, CHANGESETS, AT_STAMP)
    assert same_state(_meta(AT_STAMP), DIFF_HASH, CHANGESETS, {})
    assert same_state(_meta(AT_STAMP), DIFF_HASH, CHANGESETS, None)


def test_old_records_without_dep_bases_match_as_before():
    assert same_state(_meta(), DIFF_HASH, CHANGESETS, MOVED)
    assert same_state(_meta(), DIFF_HASH, CHANGESETS, AT_STAMP)
    assert not same_state(_meta(), DIFF_HASH, {".": {"hash": "zzz"}}, AT_STAMP)


def _store(tmp_path, meta):
    store = LocalRecordStore(str(tmp_path))
    store.save(APP, SHORT, meta, {"working_tree": "diff\n"})
    return store


def _verstr(store, dep_bases):
    return _unique_snapshot_verstr(
        store, APP, BASE, COMMIT, DIFF_HASH, changesets=CHANGESETS, dep_bases=dep_bases
    )


def test_deps_at_their_stamp_commit_keep_the_short_verstr(tmp_path):
    store = _store(tmp_path, _meta(AT_STAMP))

    assert _verstr(store, AT_STAMP) == SHORT


def test_a_moved_dep_extends_the_verstr(tmp_path):
    store = _store(tmp_path, _meta(AT_STAMP))

    assert _verstr(store, MOVED) == f"{BASE}-dev.abcdef1.{DIFF_HASH[:12]}"
