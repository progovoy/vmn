"""The guard ``start_run()`` runs before creating a run: a new run never chains
silently under a stale open one on the same thread."""
from vmn_exp.sdk import context


def reject_reentry_without_nesting(nested):
    """Guard against silently chaining a new run under a stale open one.

    Re-running a notebook cell that never called ``run.finish()`` calls
    ``start_run()`` again on the same thread/context while the previous run is
    still open. Without this, ``pick_parent``'s env-var fallback would treat
    that still-open run's self-export as an enclosing launcher and quietly
    parent the new run to it — chaining runs nobody asked to nest, and leaking
    the old run's heartbeat thread forever.

    ``context.context_run()`` is thread/context-bound only (no process-wide
    fallback), so a different thread opening its own run — legitimate
    concurrent usage — is never affected. Pass ``nested=True`` to nest under
    the open run on purpose, mirroring mlflow's "run already active" error.
    """
    if nested:
        return
    active = context.context_run()
    if active is not None:
        raise RuntimeError(
            f"Run '{active.id}' is already active on this thread. Call its "
            ".finish() before starting another, or pass nested=True to open "
            "a nested run under it."
        )
