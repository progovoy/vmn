"""The real S3 client: boto3, imported only when an ``s3://`` store opens.

Only the CLI's composition root uses :func:`boto3_client`; the store classes
take a client (or a ``client_factory(endpoint_url)``) and never build one.
The settings are ``vmn_exp.storage.s3_base``'s.
"""
import importlib

# Every call is bounded: a stalled connection fails and is retried (adaptive
# mode: backoff with jitter plus a client-side rate limit a SlowDown lowers);
# read_timeout is per socket read, not per transfer.
CONNECT_TIMEOUT_SEC = 10
READ_TIMEOUT_SEC = 30
RETRIES = {"mode": "adaptive", "total_max_attempts": 5}
# Connections one client pools for every thread sharing it (boto3's default: 10).
MAX_POOL_CONNECTIONS = 32 * 10


def boto3_module():
    """The ``boto3`` module; ImportError naming the extra when it is missing."""
    try:
        return importlib.import_module("boto3")
    except ImportError:
        raise ImportError(
            "s3:// stores need boto3: pip install 'vmn[s3]'"
        ) from None


def boto3_client(endpoint_url=None):
    """An S3 client of a session of its own, at *endpoint_url* when given."""
    session = boto3_module().session.Session()
    config = importlib.import_module("botocore.config").Config(
        max_pool_connections=MAX_POOL_CONNECTIONS,
        connect_timeout=CONNECT_TIMEOUT_SEC,
        read_timeout=READ_TIMEOUT_SEC,
        retries=dict(RETRIES),
    )
    kwargs = {"endpoint_url": endpoint_url} if endpoint_url else {}
    return session.client("s3", config=config, **kwargs)
