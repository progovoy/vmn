#!/usr/bin/env python3
"""The purge job (plan 11 §6.3): a workspace disconnected for 7 days loses its
cache rows and its registration. The cache is derived (I2), so purging is
always safe; reconnecting rebuilds it from the bucket."""
PURGE_AFTER_SEC = 7 * 86400


def _due(ws, now):
    return ws.disconnected_at is not None and now - ws.disconnected_at >= PURGE_AFTER_SEC


def purge_disconnected(manager, cache, cache_id, now):
    """Purge every due workspace of *manager* from *cache* (``cache_id(ws)``
    is its ``workspace_id`` there); returns the purged names."""
    purged = []
    for ws in [w for w in manager.list() if _due(w, now)]:
        cache.purge_workspace(cache_id(ws))
        manager.remove(ws.name)
        purged.append(ws.name)
    return purged
