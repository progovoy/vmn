"""An S3 store learns an app's child-marker flag from the listings it already
makes of the app's prefix (the index refresher's): its state from the
listed object's size, its token from the listed ETag. So the UI's store
upkeep skips a flagged app with no read of the flag, even in a new process,
while a dropped flag is still seen as not complete and ``prune -v`` still
reads the flag itself before trusting it."""
from types import SimpleNamespace

import pytest
from s3_helpers import mocked_bucket, s3_storage

from vmn_exp.cli import prune as prune_mod
from vmn_exp.core import index as experiment_index
from vmn_exp.core.writer import create_run
from vmn_exp.storage import children_flag, s3_stats
from vmn_exp.storage.base import NO_FILE
from vmn_exp.storage.files import CHILDREN_COMPLETE_FILE
from vmn_exp.ui.store_upkeep import AppUpkeep

APP = "my_app"
CODE = "0.0.1-dev.abc.def"


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield s3_storage()


@pytest.fixture
def calls():
    seen = []
    s3_stats.add_listener(seen.append)
    yield seen
    s3_stats.remove_listener(seen.append)


def _run(storage, parent=None):
    return create_run(storage, APP, CODE, {"timestamp": "2026-01-01T00:00:00Z"}, {},
                      parent=parent)


def _reads(calls):
    return [c for c in calls if c.operation in ("GetObject", "HeadObject")]


def _flag_reads(calls):
    return [c for c in _reads(calls) if c.key.endswith(CHILDREN_COMPLETE_FILE)]


def _snap(storage):
    return experiment_index.indexed_snapshot(storage, APP, wait=True)


def _restarted():
    """The store as a new process opens it: nothing seen of its flag yet."""
    children_flag._SEEN.clear()
    return s3_storage()


def test_nothing_is_known_of_the_flag_before_a_listing(s3):
    _run(s3)
    assert _restarted().children_flag_seen(APP) is None


@pytest.mark.parametrize("list_app", ["list_verstrs", "list_record_names", "list_files"])
def test_a_listing_of_the_app_shows_a_complete_flag_and_its_token(s3, list_app):
    _run(s3)
    s3.set_children_complete(APP, True)
    fresh = _restarted()

    getattr(fresh, list_app)(APP)

    assert fresh.children_flag_seen(APP) == (True, s3.children_flag(APP))


def test_a_listing_shows_a_dropped_flag_as_not_complete(s3):
    _run(s3)
    s3.set_children_complete(APP, True)
    s3.set_children_complete(APP, False)
    fresh = _restarted()

    fresh.list_verstrs(APP)

    assert fresh.children_flag_seen(APP) == (False, s3.children_flag(APP))


def test_a_listing_shows_a_missing_flag(s3):
    _run(s3)
    fresh = _restarted()

    fresh.list_record_names(APP)

    assert fresh.children_flag_seen(APP) == (False, NO_FILE)


def test_the_flag_is_never_taken_for_a_run(s3):
    verstr = _run(s3)
    s3.set_children_complete(APP, True)

    assert s3.list_verstrs(APP) == [verstr]
    assert list(s3.list_record_names(APP)) == [verstr]
    assert list(s3.list_files(APP)) == [verstr]
    assert [n for page in s3.record_name_pages(APP) for n in page] == [verstr]


def test_a_write_of_the_flag_is_seen_without_a_read(s3, calls):
    _run(s3)
    s3.set_children_complete(APP, True)
    assert s3.children_flag_seen(APP) == (True, s3.children_flag(APP))
    s3.set_children_complete(APP, False)
    assert s3.children_flag_seen(APP) == (False, s3.children_flag(APP))


def test_a_restarted_upkeep_skips_a_flagged_app_without_reading_the_flag(s3, calls):
    outer = _run(s3)
    _run(s3, parent=outer)
    AppUpkeep(s3, APP).run(_snap(s3))
    assert s3.children_complete(APP)

    restarted = _restarted()
    snapshot = _snap(restarted)
    calls.clear()
    AppUpkeep(restarted, APP).run(snapshot)

    assert _reads(calls) == []


def test_upkeep_reflags_a_listed_drop_without_reading_the_flag(s3, calls):
    _run(s3)
    s3.set_children_complete(APP, True)
    s3_storage().set_children_complete(APP, False)  # another host drops it

    restarted = _restarted()
    snapshot = _snap(restarted)
    calls.clear()
    AppUpkeep(restarted, APP).run(snapshot)

    assert _flag_reads(calls) == []
    assert s3.children_complete(APP)


def _broken(*args):
    raise OSError("down")


def test_upkeep_does_not_flag_over_a_drop_during_its_check(s3, monkeypatch):
    outer = _run(s3)
    s3.set_children_complete(APP, False)
    restarted = _restarted()
    snapshot = _snap(restarted)
    real, other = restarted.list_verstrs, s3_storage()

    def listing(app_name):
        names = list(real(app_name))
        with monkeypatch.context() as m:
            m.setattr(other, "mark_child", _broken)
            _run(other, parent=outer)  # created after the check listed: its marker failed
        return names

    monkeypatch.setattr(restarted, "list_verstrs", listing)
    AppUpkeep(restarted, APP).run(snapshot)

    assert not s3.children_complete(APP)


def _prune(storage, version):
    args = SimpleNamespace(version=[version], keep=None, older_than=None, force=False,
                           dry_run=False, query=None, protect_tag=None)
    return prune_mod.experiment_prune(None, {}, storage, args, APP)


def test_prune_does_not_trust_a_flag_seen_before_a_drop(s3, monkeypatch):
    outer = _run(s3)
    s3.set_children_complete(APP, True)
    s3.list_verstrs(APP)
    seen = dict(children_flag._SEEN)
    other = s3_storage()
    with monkeypatch.context() as m:
        m.setattr(other, "mark_child", _broken)
        kid = _run(other, parent=outer)  # its marker failed: the flag is dropped
    children_flag._SEEN.update(seen)  # …on another host: this one saw it complete
    assert s3.children_flag_seen(APP)[0] is True

    assert _prune(s3, outer) == 0

    assert s3.exists(APP, outer) and s3.exists(APP, kid)
