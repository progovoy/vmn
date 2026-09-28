"""Compatibility for tags lacking changesets data.

Older vmn versions did not record dependency changesets in the tag message.
When encountered, goto logs a warning and skips dependency updates.

Safe to remove when: no user has tags from pre-changeset vmn that they
need to ``goto``.
"""
from version_stamp.core.logging import VMN_LOGGER


def extract_changesets_or_warn(data, version, app_name):
    """Extract changesets from stamp data, warning if absent.

    Returns the changesets dict (possibly empty if legacy tag).
    Caller is responsible for deepcopy if mutation isolation is needed.
    """
    if "changesets" not in data:
        VMN_LOGGER.warning(
            f"Version {version} was stamped by an older vmn that did not "
            f"record dependency changesets. Dependency repos will not be updated."
        )
        return {}
    return data["changesets"]
