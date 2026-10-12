"""What a local-first cache's log seed and ship cost: a run the cache itself
claimed on the remote has no remote log to seed from, so its first append
lists nothing and only the first ship lists the writer's remote log; a ship
reads the local log's unshipped tail once (the line-boundary check before it
reads one byte); and the module that seeds imports the S3 helpers only when a
seed downloads."""
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
    listings = _calls_of(host._remote, "log_objects")

    assert host.create_exclusive(APP, V, meta(V), {})
    _append(host, "a0", 0)
    host.sync_log_to_remote(APP, V, W)

    assert len(listings) == 1
    assert _remote_texts() == ["a0"]


def test_a_ship_reads_the_unshipped_local_tail_once(tmp_path):
    host = _host_a_wrote_three(tmp_path)
    reads = _calls_of(host._local, "read_file_from")

    _append(host, "a3", 3)
    host.sync_log_to_remote(APP, V, W)

    assert len([r for r in reads if r[2] == log_object_name(W)]) == 1
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
