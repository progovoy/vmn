#!/usr/bin/env python3
"""The ``indexes`` section: each watched app index's load and refresh state,
read from the refresher's watches without waiting on any index."""
import time

from vmn_exp.ui.diag.registry import rounded as _rounded


def _since(now, then):
    return None if then is None else round(now - then, 3)


def _index_entry(index, watch, alive, now):
    snapshot = getattr(index, "published", None)
    loading = getattr(snapshot, "loading", None)
    due = getattr(index, "full_listing_due", None)
    return {
        "app": getattr(index, "app_name", None),
        "path": getattr(index, "path", None),
        "generation": getattr(index, "generation", None),
        "rows": None if snapshot is None else len(snapshot.rows),
        "records": getattr(index, "record_count", None),
        "loading": None if loading is None else {"loaded": loading[0], "total": loading[1]},
        "refreshing": getattr(index, "refreshing", None),
        "since_publish_sec": _since(now, getattr(index, "published_at", None)),
        "since_refresh_sec": _since(now, getattr(index, "last_refresh_at", None)),
        "last_refresh_sec": _rounded(watch.refresh_sec),
        "refresh_failing": watch.failing,
        "since_watched_sec": _since(now, watch.touched_at),
        "refresher_alive": alive,
        "keep_warm": watch.keep_warm,
        "journaled": getattr(index, "journaled", None),
        "full_listing_due": due() if due else None,
        "drift": getattr(index, "drift", None),
    }


def indexes_section(refresher):
    """*refresher*'s watched indexes; an inline refresher watches none."""
    if not getattr(refresher, "background", False):
        return {"background": False, "watched": []}
    now = time.monotonic()
    watched = []
    for index, watch in refresher.watched():
        try:
            watched.append(_index_entry(index, watch, refresher.watching(index), now))
        except Exception as exc:  # one odd index never hides the rest
            watched.append({"app": getattr(index, "app_name", None), "error": repr(exc)})
    return {"background": True, "interval_sec": refresher.interval_sec, "watched": watched}
