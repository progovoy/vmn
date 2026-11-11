"""``vmn_exp.sdk.resolve_storage``: the public way to build a ``storage=``.

Its own function, not the core resolver re-exported: the keyword-only
parameters below are the public contract, and the core resolver stays free to
change behind it (plan 41 D10).
"""
from vmn_exp.core.storage_resolve import resolve_experiment_storage


def resolve_storage(*, dir: str | None = None, store: str | None = None,
                    bucket: str | None = None, prefix: str | None = None,
                    endpoint_url: str | None = None, repo_root=None):
    """The experiment storage for *dir* or *store* (``s3://``, ``gs://``,
    ``az://``, ``file://``, plugins); *bucket*/*prefix*/*endpoint_url* are the
    S3 shorthand. ``repo_root=False`` skips finding a checkout."""
    return resolve_experiment_storage(dir=dir, store=store, bucket=bucket, prefix=prefix,
                                      endpoint_url=endpoint_url, repo_root=repo_root)
