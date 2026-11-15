"""A store edit whose upload failed is pending, not lost (plan 40 C16).

The edit storage appends to the server's buffer before it uploads, so an edit
whose upload failed stays there and would reach the store later, with any
other upload of that run or at server exit. The next action on the workspace
therefore uploads it first, and the failed job says the edit is pending.
"""

PENDING_NOTE = (
    "The edit is kept on the server and is pending until it ships: "
    "the next action on this workspace uploads it first."
)


class PendingEditError(RuntimeError):
    pass


def _has_pending(storage):
    # Only a buffered edit storage (a bucket store) has a buffer to ask.
    return getattr(storage, "has_pending", lambda: False)()


def ship_pending_first(storage, perform):
    """*perform()* once the earlier pending edits have shipped."""
    if _has_pending(storage):
        try:
            storage.ship_pending()
        except Exception as e:
            raise PendingEditError(
                f"An earlier edit is still pending, its upload failed again: {e}. "
                "This action did not run."
            ) from e
    try:
        return perform()
    except Exception as e:
        if _has_pending(storage):
            raise PendingEditError(f"{e}\n{PENDING_NOTE}") from e
        raise
