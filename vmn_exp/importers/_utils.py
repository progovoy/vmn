"""Shared helpers for vmn_exp importers."""

from __future__ import annotations

# Artifact URI schemes that indicate a remote (non-local) store.
# Note: "mlflow-artifacts:/" is intentionally absent — it is the MLflow
# Artifacts Proxy, which is local-relative to the tracking server.
_REMOTE_SCHEMES = (
    "s3://",
    "gs://",
    "wasbs://",
    "abfss://",
    "hdfs://",
    "dbfs:/",
    "ftp://",
    "http://",
    "https://",
    "r2://",
    "azure://",
)


def is_remote_uri(uri: str) -> bool:
    """Return True when *uri* points to a remote artifact store."""
    return any(uri.startswith(scheme) for scheme in _REMOTE_SCHEMES)
