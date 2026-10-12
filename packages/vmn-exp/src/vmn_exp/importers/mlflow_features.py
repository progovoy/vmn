"""What MLflow's own tags say about a run, for finding similar runs (plan 18 §3.6).

``mlflow.*`` tags never become vmn tags. These map the ones similar runs use:
the note and branch go to the record's metadata, the source name and repo URL
to its ``imported_from``, and the user and entrypoint to a ``features`` entry
(``source: mlflow``). Values are stripped; blank ones count as absent.
Pure: no IO.
"""
from __future__ import annotations

from typing import Any

from vmn_exp.core.features import build_features_entry, is_current
from vmn_exp.core.fold_facts import features_value

NOTE = "mlflow.note.content"
BRANCH = "mlflow.source.git.branch"
USER = "mlflow.user"
SOURCE_NAME = "mlflow.source.name"
ENTRY_POINT = "mlflow.project.entryPoint"
REPO_URL = "mlflow.source.git.repoURL"


def tag(tags: dict[str, Any] | None, key: str) -> str | None:
    """*key*'s stripped value in *tags*, or None when absent or blank."""
    value = (tags or {}).get(key)
    return (value.strip() or None) if isinstance(value, str) else None


def _present(pairs) -> dict[str, str]:
    return {key: value for key, value in pairs if value}


def metadata_fields(tags) -> dict[str, str]:
    """The record metadata the tags give: ``note`` and ``branch``."""
    return _present((("note", tag(tags, NOTE)), ("branch", tag(tags, BRANCH))))


def imported_from_fields(tags) -> dict[str, str]:
    """The ``imported_from`` fields the tags give: ``source_name`` and ``repo_url``."""
    return _present((("source_name", tag(tags, SOURCE_NAME)),
                     ("repo_url", tag(tags, REPO_URL))))


def author(tags) -> dict[str, str] | None:
    """The MLflow user as a features author: an email (Databricks) is the
    ``git_user_email``, anything else the ``os_user``."""
    user = tag(tags, USER)
    if not user:
        return None
    return {"git_user_email" if "@" in user else "os_user": user, "source": "mlflow"}


def features_entry(tags, commit=None, branch=False) -> dict[str, Any]:
    """The ``features`` entry of a run with *tags*. *commit* (a
    :class:`~vmn_exp.importers.commit_changes.CommitChanges` result) adds the
    source commit's changes; *branch* puts the MLflow branch inside, for a
    record whose metadata cannot take it any more."""
    return build_features_entry(
        "mlflow",
        author=author(tags),
        entrypoint=tag(tags, ENTRY_POINT) or tag(tags, SOURCE_NAME),
        branch=tag(tags, BRANCH) if branch else None,
        **(commit or {}),
    )


def needs_features(entries, commit=lambda: None) -> bool:
    """Whether a record with log *entries* lacks the features a refresh adds:
    none at the current version, or none with the source commit's changes
    now known — ``commit()``, asked only when they decide it."""
    found = (features_value(e) for e in entries if e.get("type") == "features")
    current = [parsed[1] for parsed in found if parsed and is_current(parsed[1])]
    if not current:
        return True
    return not any(value.get("changed") for value in current) and bool(commit())
