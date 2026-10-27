"""s3bench's fast S3: a minimal asyncio S3 (GET/HEAD/PUT/LIST) with latency.

    python s3bench_fast.py --port P --latency-ms 30 --data <seed dir> --bucket B --root vmn-exp

The same interface as :mod:`uiload.s3bench_moto` (``READY <port> <objects>
<seconds>``, ``GET /__stats``), for throughput benchmarks: moto spends about
a millisecond of CPU per request under one GIL, so it saturates at ~800
requests a second — below what a cold index load issues. This one answers
from a sorted in-memory key list in tens of microseconds, every request
after ``--latency-ms`` of (non-blocking) sleep, so the client is what a
benchmark measures. Path-style requests only; ListObjectsV2 with prefix,
delimiter, start-after, continuation token, max-keys and url encoding;
single ranges.
"""
import argparse
import asyncio
import bisect
import collections
import email.utils
import hashlib
import json
import os
import sys
import time
from urllib.parse import parse_qsl, quote, unquote

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uiload.s3bench_seed import iter_objects  # noqa: E402

XMLNS = "http://s3.amazonaws.com/doc/2006-03-01/"


class Store:
    def __init__(self):
        self.objects = {}  # key -> (body, mtime, etag)
        self.names = []  # sorted keys

    def put(self, key, body, mtime=None):
        if key not in self.objects:
            bisect.insort(self.names, key)
        self.objects[key] = (body, mtime or time.time(), '"%s"' % hashlib.md5(body).hexdigest())

    def entries(self, prefix, delimiter, after):
        """``(name, object or None)`` under *prefix* past *after*: keys, and
        each common prefix once (None)."""
        names = self.names
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
            if name > after:
                yield name, self.objects[name]
            i += 1


def _xml_escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _http_date(ts):
    return email.utils.formatdate(ts, usegmt=True)


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + ".000Z"


def list_v2(store, bucket, q):
    prefix, delimiter = q.get("prefix", ""), q.get("delimiter", "")
    encode = q.get("encoding-type") == "url"
    enc = (lambda s: quote(s, safe="/")) if encode else _xml_escape
    after = q.get("continuation-token") or q.get("start-after") or ""
    max_keys = int(q.get("max-keys", 1000))
    page, truncated = [], False
    for name, obj in store.entries(prefix, delimiter, after):
        if len(page) == max_keys:
            truncated = True
            break
        page.append((name, obj))
    out = [f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="{XMLNS}">',
           f"<Name>{bucket}</Name><Prefix>{enc(prefix)}</Prefix><KeyCount>{len(page)}</KeyCount>",
           f"<MaxKeys>{max_keys}</MaxKeys><IsTruncated>{'true' if truncated else 'false'}</IsTruncated>"]
    if delimiter:
        out.append(f"<Delimiter>{enc(delimiter)}</Delimiter>")
    if encode:
        out.append("<EncodingType>url</EncodingType>")
    for name, obj in page:
        if obj is None:
            out.append(f"<CommonPrefixes><Prefix>{enc(name)}</Prefix></CommonPrefixes>")
        else:
            body, mtime, etag = obj
            out.append(f"<Contents><Key>{enc(name)}</Key><LastModified>{_iso(mtime)}</LastModified>"
                       f"<ETag>{_xml_escape(etag)}</ETag><Size>{len(body)}</Size>"
                       "<StorageClass>STANDARD</StorageClass></Contents>")
    if truncated:
        out.append(f"<NextContinuationToken>{_xml_escape(page[-1][0])}</NextContinuationToken>")
    out.append("</ListBucketResult>")
    return 200, {"Content-Type": "application/xml"}, "".join(out).encode()


def _error(status, code):
    body = f'<?xml version="1.0" encoding="UTF-8"?><Error><Code>{code}</Code></Error>'.encode()
    return status, {"Content-Type": "application/xml"}, body


def get_object(store, key, headers, head):
    obj = store.objects.get(key)
    if obj is None:
        return _error(404, "NoSuchKey")
    body, mtime, etag = obj
    out = {"ETag": etag, "Last-Modified": _http_date(mtime), "Accept-Ranges": "bytes",
           "Content-Type": "application/octet-stream"}
    status, rng = 200, headers.get("range")
    if rng and rng.startswith("bytes="):
        start, _, end = rng[6:].partition("-")
        total = len(body)
        if start == "":
            first, last = max(0, total - int(end)), total - 1
        else:
            first, last = int(start), min(int(end) if end else total - 1, total - 1)
        if first >= total:
            return _error(416, "InvalidRange")
        body, status = body[first:last + 1], 206
        out["Content-Range"] = f"bytes {first}-{last}/{total}"
    out["Content-Length"] = str(len(body))
    return status, out, (b"" if head else body)


class Server:
    def __init__(self, store, bucket, latency_sec):
        self.store, self.bucket, self.latency_sec = store, bucket, latency_sec
        self.counts = collections.Counter()

    def _count(self, method, path, query):
        kind = "LIST" if method == "GET" and "list-type" in query else method
        self.counts[kind] += 1
        if kind == "GET":
            name = path.rsplit("/", 1)[-1]
            suffix = next((s for s in (".vmx", ".vms", ".jsonl") if name.endswith(s)), None)
            self.counts[f"GET {suffix or (name if name.endswith(('.yml', '.json')) else 'other')}"] += 1

    def handle(self, method, target, headers, body):
        path, _, query = target.partition("?")
        if path == "/__stats":
            stats = dict(self.counts, cpu_sec=round(time.process_time(), 2))
            return 200, {"Content-Type": "application/json"}, json.dumps(stats).encode()
        self._count(method, path, query)
        q = dict(parse_qsl(query, keep_blank_values=True))
        bucket, _, key = unquote(path).lstrip("/").partition("/")
        if bucket != self.bucket:
            return _error(404, "NoSuchBucket")
        if method == "GET" and not key and "list-type" in q:
            return list_v2(self.store, bucket, q)
        if method in ("GET", "HEAD") and key:
            return get_object(self.store, key, headers, method == "HEAD")
        if method == "PUT" and key:
            if headers.get("if-none-match") == "*" and key in self.store.objects:
                return _error(412, "PreconditionFailed")
            self.store.put(key, body)
            return 200, {"ETag": self.store.objects[key][2]}, b""
        if method == "DELETE" and key:
            if self.store.objects.pop(key, None) is not None:
                self.store.names.remove(key)
            return 204, {}, b""
        return _error(501, "NotImplemented")

    async def connection(self, reader, writer):
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode("latin-1").split("\r\n")
                method, target, _ = lines[0].split(" ", 2)
                headers = {}
                for line in lines[1:]:
                    if ":" in line:
                        k, v = line.split(":", 1)
                        headers[k.strip().lower()] = v.strip()
                if headers.get("expect", "").lower() == "100-continue":
                    writer.write(b"HTTP/1.1 100 Continue\r\n\r\n")
                length = int(headers.get("content-length", 0) or 0)
                body = await reader.readexactly(length) if length else b""
                if target != "/__stats":
                    await asyncio.sleep(self.latency_sec)
                status, out, payload = self.handle(method, target, headers, body)
                out.setdefault("Content-Length", str(len(payload)))
                lines = [f"HTTP/1.1 {status} X"] + [f"{k}: {v}" for k, v in out.items()]
                writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + payload)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


def load(store, data, root):
    n = 0
    for key, mtime, body in iter_objects(data):
        store.objects[f"{root}/{key}"] = (body, mtime, '"%s"' % hashlib.md5(body).hexdigest())
        n += 1
    store.names = sorted(store.objects)
    return n


async def serve(port, server, ready):
    srv = await asyncio.start_server(server.connection, "127.0.0.1", port, backlog=1024)
    print(ready, flush=True)
    async with srv:
        await srv.serve_forever()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--latency-ms", type=float, default=30)
    p.add_argument("--data", required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--root", required=True)
    a = p.parse_args(argv)
    t0 = time.monotonic()
    store = Store()
    n = load(store, a.data, a.root)
    ready = f"READY {a.port} {n} {time.monotonic() - t0:.1f}"
    asyncio.run(serve(a.port, Server(store, a.bucket, a.latency_ms / 1000), ready))


if __name__ == "__main__":
    main()
