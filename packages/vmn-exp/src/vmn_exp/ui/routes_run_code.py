#!/usr/bin/env python3
"""``GET .../experiments/{verstr}/patch`` and ``.../baselines`` (plan 20 K2, K3).

``/patch`` is ``vmn-exp show --patch --json``'s ``patch`` object
(:func:`~vmn_exp.cli.views.patch_payload`) plus the ``files`` its text
changes; its ETag is the run's code identity, so a 304 skips loading the code.
``/baselines`` names the runs the Changes card can diff the run against,
answered from the app's index snapshot (:mod:`~vmn_exp.ui.readers.baselines`).
Both are read-only and lock-free.
"""
import hashlib
import json

from fastapi import HTTPException, Request
from vmn_exp.cli.views import PATCH_MAX_BYTES, patch_payload
from vmn_exp.core.code_store import CODE_MISSING
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.readers.baselines import baselines
from vmn_exp.ui.readers.patch_files import patch_files
from vmn_exp.ui.readers.patches import patch_presence
from vmn_exp.ui.responses import json_response, not_modified

# The most patch text one response carries, whatever ``max_bytes`` asks.
MAX_PATCH_BYTES = 10 * 1024 * 1024
_CODE_IDENTITY = ("code", "code_verstr", "diff_hash", "has_working_tree_patch",
                  "has_local_commits_patch", "has_untracked_files")


def code_etag(verstr, metadata, max_bytes):
    """Changes only with the run's code (its code object is immutable)."""
    identity = {k: metadata.get(k) for k in _CODE_IDENTITY}
    raw = json.dumps([verstr, identity, max_bytes], sort_keys=True, default=str)
    return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()


def _metadata(storage, app_name, verstr):
    metadata = storage.load_metadata(app_name, verstr)
    if metadata is None:
        raise HTTPException(404, f"Experiment {verstr} not found")
    return metadata


def register(app, prefix, run_storage, leaderboard_inputs, leaderboards, segment):
    """Add both routes. *run_storage(ws_name, app_tag)* → ``(storage,
    app_name, conf schema)``; *leaderboard_inputs(ws_name, app_tag)* →
    ``(snapshot, effective schema)``; *leaderboards* is the
    :class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache`; *segment(verstr)*
    returns a URL verstr or raises a 400."""
    base = f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments/{{verstr}}"

    @app.get(f"{base}/patch", dependencies=[require(VIEWER)])
    def run_patch(
        request: Request, ws_name: str, app_tag: str, verstr: str,
        max_bytes: int = PATCH_MAX_BYTES,
    ):
        segment(verstr)
        if max_bytes < 1:
            raise HTTPException(400, "max_bytes must be a positive number of bytes")
        max_bytes = min(max_bytes, MAX_PATCH_BYTES)
        storage, app_name, _ = run_storage(ws_name, app_tag)
        etag = code_etag(verstr, _metadata(storage, app_name, verstr), max_bytes)
        unchanged = not_modified(request, etag)
        if unchanged:
            return unchanged
        metadata, patches = storage.load(app_name, verstr)
        payload = patch_payload(metadata, patches, max_bytes)
        payload["files"] = patch_files(payload["text"])
        # A missing code object may be pushed later: no identity ETag then.
        missing = payload.get("reason") == CODE_MISSING
        return json_response(payload, etag=None if missing else etag, request=request)

    @app.get(f"{base}/baselines", dependencies=[require(VIEWER)])
    def run_baselines(request: Request, ws_name: str, app_tag: str, verstr: str):
        segment(verstr)
        storage, app_name, _ = run_storage(ws_name, app_tag)
        snapshot, schema = leaderboard_inputs(ws_name, app_tag)
        if snapshot.row(verstr) is None:
            _metadata(storage, app_name, verstr)
            return json_response({}, request=request)  # not indexed yet
        metadata = _metadata(storage, app_name, verstr)
        presence = patch_presence(storage, app_name, verstr, metadata)
        has_patch = presence["working_tree"] or presence["local_commits"]

        def ordered_by(metric):
            return leaderboards.ordered(snapshot, schema, sort=metric)

        found = baselines(snapshot, verstr, has_patch, schema, ordered_by)
        return json_response(found, request=request)
