"""Compatibility for deprecated "micro" release mode.

"micro" was the original name for the hotfix segment before it was
renamed to "hotfix".

Safe to remove when: no CI pipeline or user muscle-memory passes ``-r micro``.
"""


def normalize_release_mode(mode):
    """Map legacy "micro" to "hotfix". Returns mode unchanged otherwise."""
    if mode == "micro":
        return "hotfix"
    return mode
