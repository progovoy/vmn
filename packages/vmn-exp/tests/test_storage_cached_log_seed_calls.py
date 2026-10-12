"""What a local-first cache's log ship costs: a new run's first ship lists
the remote's log streams once and a later one not at all; a ship reads the
local log's unshipped tail once; and importing the cache leaves the S3
helpers unloaded."""
import os
import subprocess
import sys

from s3_helpers import cached_host, meta
from test_storage_cached_log_seed import (  # noqa: F401
    APP,
    V,
    W,
    _append,
    _bucket,
    _host_a_wrote_three,
    _remote_texts,
)
from vmn_exp.core.writer import own_stream
from vmn_exp.storage.files import log_object_name


def _calls_of(obj, method):
    calls, real = [], getattr(obj, method)

    def counted(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    setattr(obj, method, counted)
    return calls


def test_creating_and_shipping_a_new_run_lists_its_remote_log_once(tmp_path):
    host = cached_host(tmp_path, "a")
    listings = _calls_of(host._remote, "log_object_groups")

    assert host.create_exclusive(APP, V, meta(V), {})
    _append(host, "a0", 0)
    host.sync_log_to_remote(APP, V, own_stream(host, APP, V))
    _append(host, "a1", 1)
    host.sync_log_to_remote(APP, V, own_stream(host, APP, V))

    assert len(listings) == 1
    assert _remote_texts() == ["a0", "a1"]


def test_a_ship_reads_the_unshipped_local_tail_once(tmp_path):
    host = _host_a_wrote_three(tmp_path)
    reads = _calls_of(host._local, "read_file_from")

    _append(host, "a3", 3)
    stream = own_stream(host, APP, V)
    host.sync_log_to_remote(APP, V, stream)

    assert len([r for r in reads if r[2] == log_object_name(stream)]) == 1
    assert _remote_texts() == ["a0", "a1", "a2", "a3"]


def test_importing_the_cache_leaves_the_s3_helpers_unloaded():
    script = (
        "import sys, vmn_exp.storage.cached\n"
        "print('vmn_exp.storage.s3_base' in sys.modules)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True,
        env=dict(os.environ), check=True,
    ).stdout
    assert out.strip() == "False"
