#!/usr/bin/env python3
"""A run detail's ``env``: the run's ``env.yml``, else its metadata summary."""
import time

import yaml

from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.listed_reads import store_identity

_ENV_SIZE_CAP = 256 * 1024  # 256 KB
ENV_MISS_TTL_SEC = 300
_ENV_MISSES = LRU(4096)  # (store, app, verstr) -> (when, None): env.yml missing


def env_payload(raw, metadata):
    """``env`` payload for the detail: full dict when env.yml fits, else summary.

    Returns the full env dict when env.yml (*raw*, bytes or None) is present
    and at most ``_ENV_SIZE_CAP`` bytes.  When the file is larger, returns the
    compact summary from *metadata* with ``truncated: True`` added.  Returns
    ``None`` when neither env.yml nor a summary is available.
    """
    if raw is not None:
        if len(raw) <= _ENV_SIZE_CAP:
            try:
                return yaml.safe_load(raw)
            except Exception:
                pass
        summary = metadata.get("env")
        return dict(summary, truncated=True) if summary else None
    return metadata.get("env") or None


def env_file(storage, app_name, verstr):
    """``env.yml``'s bytes, or None. Most runs without an env capture have
    none, so a miss is remembered for :data:`ENV_MISS_TTL_SEC`: a polling
    run page asks for it once, not on every poll."""
    def read():
        return time.monotonic(), storage.load_file(app_name, verstr, "env.yml")

    return _ENV_MISSES.get(
        (store_identity(storage), app_name, verstr), read,
        valid=lambda hit: time.monotonic() - hit[0] < ENV_MISS_TTL_SEC,
        store=lambda hit: hit[1] is None,
    )[1]


def detail_env(storage, app_name, verstr, raw, metadata):
    """The detail's ``env`` from *raw* (:func:`env_file`'s answer). A miss is
    read again for a run whose metadata says it wrote ``env.yml`` (its env
    summary): the miss may predate the file."""
    if raw is None and metadata.get("env"):
        raw = storage.load_file(app_name, verstr, "env.yml")
    return env_payload(raw, metadata)
