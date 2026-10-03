"""An abandoned revision claim (claimed, body never written) never blocks saves."""
import pytest
from s3_helpers import mocked_bucket, s3_storage

from vmn_exp.reports import store as rstore
from vmn_exp.storage.areas import REPORTS
from vmn_exp.storage.local import LocalSnapshotStorage


@pytest.fixture(autouse=True)
def short_settle(monkeypatch):
    monkeypatch.setattr(rstore, "_SETTLE_SEC", 0.2)


@pytest.fixture(params=["local", "s3"])
def storage(request, tmp_path, monkeypatch):
    if request.param == "local":
        yield LocalSnapshotStorage(str(tmp_path / "store"), "runs")
        return
    with mocked_bucket(monkeypatch):
        yield s3_storage()


def _abandon(storage, rid, n):
    """Leave ``v<n>`` claimed with no body, like a writer that crashed."""
    area = storage.in_area(REPORTS)
    area.delete(rid, f"v{n}")
    assert area.create_exclusive(rid, f"v{n}", {"verstr": f"v{n}"}, {})


def test_abandoned_v1_does_not_block_first_save(storage):
    rid = rstore.create(storage, "t", "lost")
    _abandon(storage, rid, 1)
    report = rstore.get(storage, rid)
    assert report["rev"] == 0
    rev = rstore.save(storage, rid, report["rev"], "saved")
    assert isinstance(rev, int) and rev > 1
    got = rstore.get(storage, rid)
    assert got["rev"] == rev and got["body"] == "saved"
    assert rstore.save(storage, rid, rev, "next") == rev + 1


def test_abandoned_later_claim_does_not_block_save(storage):
    rid = rstore.create(storage, "t", "one")
    assert rstore.save(storage, rid, 1, "two") == 2
    rstore.save(storage, rid, 2, "lost")
    _abandon(storage, rid, 3)
    report = rstore.get(storage, rid)
    assert report["rev"] == 2 and report["body"] == "two"
    rev = rstore.save(storage, rid, 2, "mine")
    assert isinstance(rev, int) and rev > 3
    assert rstore.revision(storage, rid, rev)["base"] == 2
    assert rstore.get(storage, rid)["body"] == "mine"


def test_complete_revision_past_abandoned_claim_is_a_conflict(storage):
    rid = rstore.create(storage, "t", "one")
    _abandon(storage, rid, 1)
    winner = rstore.save(storage, rid, 0, "theirs")
    result = rstore.save(storage, rid, 0, "mine")
    assert isinstance(result, rstore.Conflict)
    assert result.rev == winner and result.body == "theirs"
