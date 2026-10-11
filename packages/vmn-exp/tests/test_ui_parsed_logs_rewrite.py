"""The run-detail log cache of a ``vmn-exp ui`` over a local root (no remote)
parses a log again once a local-first cache over that root rewrote it into a
bigger file (a merge of the remote's lines, :mod:`cached_log_merge`), rather
than read on from an offset that no longer lines up."""
from s3_helpers import cached_host
from test_index_log_rewrite import LONG, _host_a_shipped, _params, bucket  # noqa: F401
from test_index_log_rewrite_offline import APP, V, W, _offline, _tags
from test_storage_cached_log_seed import _note
from test_storage_cached_log_seed_failed import _remote_listing_fails_once
from vmn_exp.core.log import effective_params, load_log
from vmn_exp.ui.readers.parsed_logs import ParsedLogs


def test_the_log_cache_parses_a_log_an_online_cache_merged_again(
    tmp_path, bucket  # noqa: F811
):
    _host_a_shipped(tmp_path, _params(0, lr=0.1, layers=4))
    b = cached_host(tmp_path, "b")
    _remote_listing_fails_once(b)
    assert b.append_log_entry(APP, V, W, _note(LONG, 10))  # the local copy: LONG only
    ui = _offline(tmp_path, "b")
    cache = ParsedLogs()
    cache.get(ui, APP, V, load_log)

    online = cached_host(tmp_path, "b")
    assert online.append_log_entry(APP, V, W, _tags(11, k="v"))
    online.sync_log_to_remote(APP, V, W)  # merges: the remote's lines, then b's

    snap, full = cache.get(ui, APP, V, load_log), load_log(ui, APP, V)
    assert [e["type"] for e in full] == ["params", "note", "tags"]
    assert snap.log() == full
    assert snap.params == effective_params(full) == {"lr": 0.1, "layers": 4}
