"""s3bench's S3: a moto server with real-S3-like latency, loaded from a seed dir.

    python s3bench_moto.py --port P --latency-ms 30 --data <seed dir> --bucket B --root vmn-exp

Each request sleeps ``--latency-ms`` before moto answers it, on its own
thread, so concurrent requests overlap like they do against S3. The seeded
objects go straight into moto's backend (no HTTP) with their seeded
``LastModified``, then the process prints ``READY <port> <objects> <seconds>``.

Moto lists by scanning (and sorting) every key under the prefix for each
page, which at 10^5-10^6 keys would make the fake S3 itself the bottleneck;
:func:`install` makes listings bisect a sorted key index instead (same
results; rebuilt when the bucket's key count changes — the UI only reads).
``GET /__stats`` answers the request counts per method (LIST =
ListObjectsV2) and the process's CPU seconds, so a saturated fake S3 shows.
"""
import argparse
import bisect
import collections
import datetime
import json
import os
import sys
import threading
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from moto.core import DEFAULT_ACCOUNT_ID
from moto.moto_server.werkzeug_app import DomainDispatcherApplication, create_backend_app
from moto.s3.models import FakeDeleteMarker, S3Backend, s3_backends
import uvicorn
from uvicorn.middleware.wsgi import WSGIMiddleware

from uiload.s3bench_seed import iter_objects

_SORTED = {}
_SORTED_LOCK = threading.Lock()


def _sorted_names(bucket):
    """*bucket*'s key names, sorted; cached while its key count holds."""
    with _SORTED_LOCK:
        cached = _SORTED.get(id(bucket))
        if cached and cached[0] == len(bucket.keys):
            return cached[1]
        names = sorted(bucket.keys.keys())
        _SORTED[id(bucket)] = (len(names), names)
        return names


def _entries(bucket, prefix, delimiter, after=""):
    """``(name, key or None)`` under *prefix* past *after*, in order: keys,
    and each common prefix once (key None)."""
    names = _sorted_names(bucket)
    i = bisect.bisect_left(names, max(prefix, after))
    while i < len(names) and names[i].startswith(prefix):
        name = names[i]
        rest = name[len(prefix):]
        if delimiter and delimiter in rest:
            folder = prefix + rest.split(delimiter)[0] + delimiter
            if folder > after:
                yield folder, None
            i = bisect.bisect_left(names, folder[:-1] + chr(ord(delimiter) + 1), i)
            continue
        key = bucket.keys.get(name)
        if name > after and key is not None and not isinstance(key, FakeDeleteMarker):
            yield name, key
        i += 1


def _fast_list_objects(self, bucket, prefix, delimiter, marker, max_keys):
    """:meth:`S3Backend.list_objects` over the sorted index."""
    keys, folders = [], []
    for name, key in _entries(bucket, prefix or "", delimiter):
        (folders.append(name) if key is None else keys.append(key))
    if marker:
        keys = self._get_results_from_token(keys, self._pagination_tokens.get(marker) or marker)
    if max_keys is None:
        return keys, folders, False, None
    keys, truncated, next_marker = self._truncate_result(keys, max_keys)
    return keys, folders, truncated, next_marker


def _fast_list_objects_v2(self, bucket, prefix, delimiter, continuation_token, start_after, max_keys):
    """:meth:`S3Backend.list_objects_v2` reading only the page it answers."""
    after = (self._pagination_tokens.get(continuation_token) if continuation_token
             else start_after) or ""
    page = []
    for name, key in _entries(bucket, prefix or "", delimiter, after):
        page.append(name if key is None else key)
        if len(page) > max_keys:
            break
    return self._truncate_result(page, max_keys)


def install():
    """Patch moto's listings; returns the undo."""
    originals = S3Backend.list_objects, S3Backend.list_objects_v2
    S3Backend.list_objects, S3Backend.list_objects_v2 = _fast_list_objects, _fast_list_objects_v2

    def undo():
        S3Backend.list_objects, S3Backend.list_objects_v2 = originals
    return undo


# Concurrent requests served at once: above the 64 pooled connections of
# vmn's S3 client, so the latency overlaps as on real S3.
WSGI_THREADS = 128


def object_kind(path):
    """A GET's object kind, to see which reads a phase spends its requests on."""
    name = path.rsplit("/", 1)[-1]
    for suffix in (".vmx", ".vms", ".jsonl"):
        if name.endswith(suffix):
            return suffix
    return name if name.endswith((".yml", ".yaml", ".json")) else "other"


class Latency:
    """WSGI middleware: *latency_sec* before each request, and per-method counts."""

    def __init__(self, app, latency_sec):
        self.app, self.latency_sec = app, latency_sec
        self.counts = collections.Counter()
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        if environ.get("PATH_INFO") == "/__stats":
            with self.lock:
                stats = dict(self.counts, cpu_sec=round(time.process_time(), 2))
            start_response("200 OK", [("Content-Type", "application/json")])
            return [json.dumps(stats).encode()]
        kind = environ["REQUEST_METHOD"]
        if kind == "GET" and "list-type=2" in environ.get("QUERY_STRING", ""):
            kind = "LIST"
        with self.lock:
            self.counts[kind] += 1
            if kind == "GET":
                self.counts[f"GET {object_kind(environ.get('PATH_INFO', ''))}"] += 1
        time.sleep(self.latency_sec)
        return self.app(environ, start_response)


def load(data, bucket, root):
    backend = s3_backends[DEFAULT_ACCOUNT_ID]["global"]
    backend.create_bucket(bucket, "us-east-1")
    n = 0
    for key, mtime, body in iter_objects(data):
        fake = backend.put_object(bucket, f"{root}/{key}", body, disable_notification=True)
        fake.last_modified = datetime.datetime.utcfromtimestamp(mtime)
        n += 1
    return n


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--latency-ms", type=float, default=30)
    p.add_argument("--data", required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--root", required=True)
    a = p.parse_args(argv)
    install()
    t0 = time.monotonic()
    n = load(a.data, a.bucket, a.root)
    app = Latency(DomainDispatcherApplication(create_backend_app), a.latency_ms / 1000)
    # uvicorn, not werkzeug's dev server: that one closes every connection,
    # and a benchmark's worth of TIME_WAIT sockets exhausts the ephemeral ports.
    config = uvicorn.Config(WSGIMiddleware(app, workers=WSGI_THREADS), host="127.0.0.1",
                            port=a.port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    serving = threading.Thread(target=server.run, daemon=True)
    serving.start()
    while not server.started:
        if not serving.is_alive():
            raise SystemExit(f"S3 server failed to start on port {a.port}")
        time.sleep(0.05)
    print(f"READY {a.port} {n} {time.monotonic() - t0:.1f}", flush=True)
    serving.join()


if __name__ == "__main__":
    main()
