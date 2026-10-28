#!/usr/bin/env python3
"""The S3 backend's client and key helpers, shared by its listing, record and
log halves (:mod:`snapshot_storage_s3`)."""

import copy
import datetime
import email.utils

from vmn_exp._base import VMN_LOGGER
from vmn_exp.storage.files import checked_app_path, safe_verstr
from vmn_exp.storage.registry import missing_extra
from vmn_exp.storage.s3_stats import instrument
from vmn_exp.storage.fanout import fan_out

# Requests one call keeps in flight: enough to hide S3 latency at 10k+ runs.
S3_WORKERS = 10
# Connections a client pools, for every thread sharing it (boto3's default: 10):
# the threads starting fan-outs plus the workers fan-outs share (fanout).
MAX_POOL_CONNECTIONS = 32 * S3_WORKERS
# Every call is bounded: a stalled connection fails and is retried (adaptive
# mode: standard's backoff with jitter and retry quota, plus a client-side
# rate limit that a throttling store's SlowDown lowers) instead of holding an
# index refresh; read_timeout is per socket read, not per transfer.
CONNECT_TIMEOUT_SEC = 10
READ_TIMEOUT_SEC = 30
RETRIES = {"mode": "adaptive", "total_max_attempts": 5}
MISSING_CODES = ("404", "NoSuchKey", "NotFound")
TAKEN_CODES = ("412", "PreconditionFailed", "409", "ConditionalRequestConflict")


def error_code(exc):
    return ((getattr(exc, "response", None) or {}).get("Error") or {}).get("Code")


def is_missing(exc):
    """Whether *exc* says the object does not exist (not an access/transport error)."""
    return error_code(exc) in MISSING_CODES or "NoSuchKey" in str(exc)


def is_taken(exc):
    """Whether *exc* is a failed write precondition (someone else got there)."""
    return error_code(exc) in TAKEN_CODES


def parallel_map(fn, items):
    """``[fn(item)]`` in order, at most :data:`S3_WORKERS` at a time, within
    the workers all fan-outs share (:mod:`~vmn_exp.storage.fanout`)."""
    return fan_out(fn, items, S3_WORKERS, "vmn-s3-parallel")


def app_key(app_name):
    """The app's key segment: the tag form (``root/svc`` → ``root-svc``)."""
    return app_name.replace("/", "-")


def boto3_client(endpoint_url=None):
    """A client of a session of its own that parses timestamps with
    :func:`parse_timestamp` (the default session's clients keep botocore's)."""
    session = boto3_client_module().session.Session()
    session._session.get_component("response_parser_factory").set_parser_defaults(
        timestamp_parser=parse_timestamp)
    return _client(session, endpoint_url)


def sigv4_client(endpoint_url=None):
    """A client that presigns with SigV4 (``X-Amz-Expires`` bounded URLs):
    one per presigned URL, so the default session's (no session to build)."""
    return _client(boto3_client_module(), endpoint_url, signature_version="s3v4")


def _client(session, endpoint_url, **config):
    from botocore.config import Config

    # A pooled connection per concurrent reader (the index's and parallel_map's);
    # boto3's default of 10 queues the rest.
    config = Config(max_pool_connections=MAX_POOL_CONNECTIONS, connect_timeout=CONNECT_TIMEOUT_SEC,
                    read_timeout=READ_TIMEOUT_SEC, retries=dict(RETRIES), **config)
    kwargs = {"endpoint_url": endpoint_url} if endpoint_url else {}
    return instrument(session.client("s3", config=config, **kwargs))


def parse_timestamp(value):
    """botocore's ``parse_timestamp`` without dateutil for what S3 sends
    (ISO 8601 UTC in listings, RFC 1123 in headers): dateutil took ~25 µs a
    timestamp, a 1000-object LIST ~25 ms of CPU under the GIL."""
    if isinstance(value, str):
        try:
            if value.endswith("Z") and "T" in value:
                return datetime.datetime.fromisoformat(_six_digits(value[:-1]) + "+00:00")
            if value.endswith(" GMT"):
                return email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            pass
    from botocore.utils import parse_timestamp as botocore_parse

    return botocore_parse(value)


def _six_digits(text):
    """*text*'s fraction of a second padded to the six digits fromisoformat
    (3.9) takes."""
    head, dot, fraction = text.partition(".")
    return f"{head}.{fraction[:6].ljust(6, '0')}" if dot else head


def boto3_client_module():
    try:
        import boto3
    except ImportError:
        raise missing_extra("boto3", "s3") from None
    return boto3


class S3Base:
    """``client`` speaks the boto3 S3 client subset these halves use; other
    object stores pass an adapter (:mod:`vmn_exp.storage.object_client`)."""

    scheme = "s3"

    def __init__(self, bucket, prefix="vmn/snapshots", endpoint_url=None, client=None):
        self.bucket = bucket
        self.prefix = prefix
        self.endpoint_url = endpoint_url
        self._s3 = client or boto3_client(endpoint_url)
        self._own_client = client is None  # not another object store's adapter

    @property
    def area(self):
        return self.prefix.rpartition("/")[2]

    def _open_area(self, name):
        """This store's sibling area: ``<root>/<name>``, sharing the client."""
        clone = copy.copy(self)
        clone.__dict__.pop("_areas", None)
        clone.prefix = f"{self.prefix.rpartition('/')[0]}/{name}".lstrip("/")
        return clone

    # -- keys -----------------------------------------------------------------

    def _key_prefix(self, app_name, verstr=None):
        base = f"{self.prefix}/{app_key(checked_app_path(app_name))}"
        return f"{base}/{safe_verstr(verstr)}" if verstr else base

    def _record_prefix(self, app_name, verstr):
        return self._key_prefix(app_name, verstr)

    # -- client ---------------------------------------------------------------

    def _head(self, key):
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            if not is_missing(e):
                VMN_LOGGER.warning(f"S3 error checking {key}: {e}")
            return False

    def _get(self, key):
        try:
            return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as e:
            if not is_missing(e):
                VMN_LOGGER.debug(f"S3 error reading {key}", exc_info=True)
            return None

    def _get_or_raise(self, key):
        """*key*'s bytes, None when it is missing; any other failure raises."""
        return self._get_with_etag(key)[0]

    def _get_with_etag(self, key):
        """``(bytes, etag)`` of *key*, ``(None, None)`` when it is missing."""
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            if is_missing(e):
                return None, None
            raise
        return resp["Body"].read(), resp["ETag"]

    def _put(self, key, data, **kwargs):
        body = data.encode("utf-8") if isinstance(data, str) else data
        return self._s3.put_object(Bucket=self.bucket, Key=key, Body=body, **kwargs)

    def _create(self, key, data):
        """Create *key* unless it exists (``If-None-Match``); whether it did."""
        try:
            self._put(key, data, IfNoneMatch="*")
        except Exception as e:
            if is_taken(e):
                return False
            raise
        return True

    def _pages(self, **params):
        """Every ``list_objects_v2`` page for *params*, following continuations."""
        params = dict(params, Bucket=self.bucket)
        while True:
            page = self._s3.list_objects_v2(**params)
            yield page
            if not page.get("IsTruncated"):
                return
            params["ContinuationToken"] = page["NextContinuationToken"]

    def _objects(self, prefix):
        for page in self._pages(Prefix=prefix):
            yield from page.get("Contents", [])

    def _common_prefixes(self, prefix):
        found = []
        for page in self._pages(Prefix=prefix, Delimiter="/"):
            found.extend(cp["Prefix"] for cp in page.get("CommonPrefixes", []))
        return found
