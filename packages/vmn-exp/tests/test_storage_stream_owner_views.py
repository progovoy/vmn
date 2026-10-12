"""Processes that see one record directory under another ``st_dev`` (a
container, virtiofs, an overlay over a bind mount) are one copy when the
inode and the path agree; under another path each view keeps an owner of its
own. Either way alternating appends never mint again and again, and no view
ships another's stream."""
import pytest
from multi_clone_helpers import (
    APP,
    V,
    block,
    one_host_bucket,
    remote_metric_values,
    remote_tag_keys,
    stream,
    tag,
)
from s3_helpers import cached_host, meta
from vmn_exp.storage import stream_owner


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


class _Views:
    """Switch the view of every record directory: the host's or a
    container's (another st_dev; with *path*, another realpath too)."""

    def __init__(self, monkeypatch, path=None):
        self._real, self.container, self._path = stream_owner._where, False, path
        monkeypatch.setattr(stream_owner, "_where", self._where)

    def _where(self, record_dir):
        ident, real = self._real(record_dir)
        if not self.container or ident is None:
            return ident, real
        return [ident[0] + 1, ident[1]], (self._path + real if self._path else real)


def _alternate(tmp_path, views, turns=6):
    seen = []
    for i in range(turns):
        views.container = bool(i % 2)
        h = cached_host(tmp_path, "a")
        own = stream(h)
        seen.append(own)
        h.append_log_entry(APP, V, own, tag(i, f"k{i}"))
        h.append_metric_block(APP, V, own, block(float(i), start=i * 10))
        h.sync_log_to_remote(APP, V, own)
        h.sync_metrics_to_remote(APP, V, own)
    return seen


def test_a_container_view_at_the_same_path_is_the_same_copy(tmp_path, monkeypatch):
    assert cached_host(tmp_path, "a").create_exclusive(APP, V, meta(V), {})
    views = _Views(monkeypatch)

    seen = _alternate(tmp_path, views)

    assert len(set(seen)) == 1
    assert remote_tag_keys() == [f"k{i}" for i in range(6)]
    assert remote_metric_values() == [float(i) for i in range(6)]


def test_a_container_view_at_another_path_keeps_one_owner_of_its_own(tmp_path, monkeypatch):
    assert cached_host(tmp_path, "a").create_exclusive(APP, V, meta(V), {})
    views = _Views(monkeypatch, path="/mnt")

    seen = _alternate(tmp_path, views)

    assert len(set(seen)) == 2
    assert len(set(seen[0::2])) == 1 and len(set(seen[1::2])) == 1
    assert remote_tag_keys() == [f"k{i}" for i in range(6)]
    assert remote_metric_values() == [float(i) for i in range(6)]
