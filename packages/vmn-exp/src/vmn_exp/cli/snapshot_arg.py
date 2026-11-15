"""The snapshot a ``create``/``run`` records from, when it is given one."""


def from_snapshot_metadata(args, env):
    """``--from-snapshot``, else *env*'s ``VMN_SNAPSHOT_METADATA``."""
    return getattr(args, "from_snapshot", None) or env.get("VMN_SNAPSHOT_METADATA")
