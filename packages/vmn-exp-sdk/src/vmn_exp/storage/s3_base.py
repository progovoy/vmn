#!/usr/bin/env python3
"""The S3 backend's client, shared by its listing, record and log halves
(:mod:`vmn_exp.storage.s3`); key helpers and object primitives are core's
(:mod:`version_stamp.store.s3_base`), error codes and client settings too.

:data:`S3_WORKERS` requests a call keeps in flight hide S3 latency at 10k+
runs; a client pools :data:`MAX_POOL_CONNECTIONS` for every thread sharing
it: the threads starting fan-outs plus the workers fan-outs share (fanout)."""

import datetime
import email.utils
import functools
import os

from version_stamp.store.areas import app_key  # noqa: F401  (re-exported)
from version_stamp.store.s3_base import S3_WORKERS, S3ObjectBase
from version_stamp.store.s3_client import (  # noqa: F401  (re-exported)
    CONNECT_TIMEOUT_SEC,
    MAX_POOL_CONNECTIONS,
    READ_TIMEOUT_SEC,
    RETRIES,
)
from version_stamp.store.s3_errors import (  # noqa: F401  (re-exported)
    MISSING_CODES,
    TAKEN_CODES,
    error_code,
    is_missing,
    is_taken,
    put_condition,
)
from vmn_exp.storage.registry import missing_extra
from vmn_exp.storage.s3_prefix_cap import cap_prefixes
from vmn_exp.storage.s3_stats import instrument
from vmn_exp.storage.fanout import fan_out
from vmn_exp.storage.fork_proxies import child_factory, environment_proxies_only
from vmn_exp.storage.per_process import PerProcess


def parallel_map(fn, items):
    """``[fn(item)]`` in order, at most :data:`S3_WORKERS` at a time, within
    the workers all fan-outs share (:mod:`~vmn_exp.storage.fanout`)."""
    return fan_out(fn, items, S3_WORKERS, "vmn-s3-parallel")


def boto3_client(endpoint_url=None, proxies=None, *, env):
    """A client of a session of its own that parses timestamps with
    :func:`parse_timestamp` (the default session's clients keep botocore's);
    *proxies* given, botocore does not look them up. *env*: what its prefix
    cap is read from (:mod:`~vmn_exp.storage.s3_prefix_cap`)."""
    session = boto3_client_module().session.Session()
    session._session.get_component("response_parser_factory").set_parser_defaults(
        timestamp_parser=parse_timestamp)
    return _client(session, endpoint_url, env, **({} if proxies is None else {"proxies": proxies}))


def sigv4_client(endpoint_url=None):
    """A client that presigns with SigV4 (``X-Amz-Expires`` bounded URLs):
    one per presigned URL, so the default session's (no session to build)."""
    _DEFAULT_SESSION_OWNED.get()
    # Presigning sends nothing: the prefix cap's default never matters.
    return _client(boto3_client_module(), endpoint_url, {}, signature_version="s3v4")


def _forget_inherited_default_session():
    """In a forked child: drop the default session it inherited (its
    credential cache and refresh lock are the parent's)."""
    boto3_client_module().DEFAULT_SESSION = None
    environment_proxies_only()
    return True


_DEFAULT_SESSION_OWNED = PerProcess(_forget_inherited_default_session, value=True)


def _client(session, endpoint_url, env, **config):
    from botocore.config import Config

    # A pooled connection per concurrent reader (the index's and parallel_map's);
    # boto3's default of 10 queues the rest.
    config = Config(max_pool_connections=MAX_POOL_CONNECTIONS, connect_timeout=CONNECT_TIMEOUT_SEC,
                    read_timeout=READ_TIMEOUT_SEC, retries=dict(RETRIES), **config)
    kwargs = {"endpoint_url": endpoint_url} if endpoint_url else {}
    # Capped first: a call's wait for its prefix's slot is not its latency.
    return instrument(cap_prefixes(session.client("s3", config=config, **kwargs), env))


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


def _injected(pid):
    raise RuntimeError(
        f"this store's client was injected in pid {pid}; a forked child cannot reuse "
        "its connections: open the store again in the child (or pass client_factory)"
    )


class S3Base(S3ObjectBase):
    """Core's object primitives (:class:`~version_stamp.store.s3_base.S3ObjectBase`)
    over a per-process, instrumented and prefix-capped client. ``client``
    speaks the boto3 S3 client subset these halves use; other object stores
    pass an adapter (:mod:`vmn_exp.storage.object_client`)."""

    def __init__(self, bucket, prefix="vmn/snapshots", endpoint_url=None, client=None,
                 client_factory=None, options=None, *, env=None):
        """*client_factory* builds *client* again in a forked child; without
        one an injected *client* refuses use there. *options*: the store
        URI's query options (:meth:`uri_options`). *env*: the host's
        environment its per-host index cache dir and its own client's
        prefix cap resolve from; None keeps no per-host cache and the
        default cap.

        Not ``super().__init__``: core's assigns ``_s3``, a per-process
        property here."""
        self.bucket = bucket
        self.prefix = prefix
        self.endpoint_url = endpoint_url
        self._options = dict(options or {})
        self._env = env
        # Not another object store's adapter.
        self._own_client = client is None and client_factory is None
        if self._own_client:
            build = functools.partial(boto3_client, env={} if env is None else env)
            client = build(endpoint_url)
            client_factory = child_factory(build, endpoint_url, client)
        elif client is None:
            client = client_factory()
        # Area clones share it: one client and connection pool per process.
        self._clients = PerProcess(client_factory or functools.partial(_injected, os.getpid()),
                                   value=client)

    def uri_options(self, scheme):
        return dict(self._options) if scheme == self.scheme else {}

    @property
    def _s3(self):
        return self._clients.get()

    # Fan-outs run in the workers all of them share (fanout), not a pool per call.
    _map = staticmethod(parallel_map)

    def _open_area(self, name):
        """Core's sibling area, minus this store's cached area clones."""
        clone = super()._open_area(name)
        clone.__dict__.pop("_areas", None)
        return clone
