"""The real IO vmn's composition roots hand down: the one home of the real
implementations (docs/plans/35-core-io-behind-interfaces.md), so code below
the CLI that binds real IO (``version_stamp.api`` wrappers) never imports the CLI.

``real_store_io()``: what :func:`version_stamp.snapshot.stores.open_stores`
takes: ``os.environ``, a boto3 client factory (boto3 imported on first use)
and the clocks.
"""
import os
import time


def _boto3_client(endpoint_url):
    from version_stamp.store.s3_client import boto3_client

    return boto3_client(endpoint_url)


def real_store_io():
    return dict(env=os.environ, s3_client_factory=_boto3_client,
                now=time.time, monotonic=time.monotonic, sleep=time.sleep)
