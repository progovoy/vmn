#!/usr/bin/env python3
"""What an answer over an index snapshot still loading says (plan 33 §2.2):
``indexing`` ``{loaded, total}`` (total None while the store has not named
its runs yet), on experiments-status and every board answer, so a partial
board is never taken for the whole one."""
from vmn_exp.ui.responses import memoized_json_response


def with_indexing(payload, snapshot):
    """*payload* (a dict) with ``indexing`` while *snapshot*'s index is
    still loading chunk by chunk."""
    if snapshot.loading is None or not isinstance(payload, dict):
        return payload
    loaded, total = snapshot.loading
    return dict(payload, indexing={"loaded": loaded, "total": total})


def indexed_response(request, etag, snapshot, payload_of, bodies):
    """:func:`~vmn_exp.ui.responses.memoized_json_response` of a board
    answer over *snapshot*: while it loads, the payload carries ``indexing``
    and the ETag the load's progress, so a client's cached loading answer is
    replaced as the load moves on or ends."""
    if snapshot.loading is not None:
        etag = "{}.indexing.{}.{}".format(etag, *snapshot.loading)
    return memoized_json_response(
        request, etag, lambda: with_indexing(payload_of(), snapshot), bodies)
