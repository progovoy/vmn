"""Compatibility with vmn 0.3.9 tag format.

0.3.9 tags used a `.0` suffix and "Automatic" as the tag message.
Version info was stored in the commit message rather than the tag message.

Safe to remove when: all repos have been re-stamped with vmn >= 0.8.4
(no 0.3.9-era tags remain that users need to `show`/`goto`).
"""
from version_stamp.core.logging import VMN_LOGGER


def try_tag_with_dot_zero_suffix(repo_backend, tag_name):
    """Fall back to ``{tag_name}.0`` when the tag doesn't exist.

    Returns ``(resolved_tag_name, tag_object)`` or ``(tag_name, None)``.
    """
    try:
        _tag_name = f"{tag_name}.0"
        o = repo_backend.tag(f"refs/tags/{_tag_name}")
        return _tag_name, o
    except Exception:
        VMN_LOGGER.debug("Logged exception: ", exc_info=True)
        return tag_name, None


def try_commit_with_dot_zero_suffix(repo_backend, tag_name):
    """Fall back to ``{tag_name}.0`` when resolving a commit from a tag name.

    Returns ``(resolved_tag_name, commit_object)`` or ``(tag_name, None)``.
    """
    try:
        _tag_name = f"{tag_name}.0"
        commit_obj = repo_backend.commit(_tag_name)
        return _tag_name, commit_obj
    except Exception:
        return tag_name, None


def parse_automatic_tag_message(repo_backend, tag_name, ver_info):
    """Parse version info from a 0.3.9 "Automatic" tag.

    ``ver_info`` is the already-parsed (non-dict) value from the tag message.
    When it starts with "Automatic", the real version info lives in the commit
    message. Injects missing ``prerelease``/``prerelease_count`` fields for
    forward compatibility.

    Returns the parsed ver_info dict, or None if not a 0.3.9 tag.
    """
    import yaml

    if not str(ver_info).startswith("Automatic"):
        return None

    commit_msg = yaml.safe_load(repo_backend.commit(tag_name).message)
    if commit_msg is not None and "stamping" in commit_msg:
        commit_msg["stamping"]["app"]["prerelease"] = "release"
        commit_msg["stamping"]["app"]["prerelease_count"] = {}

    return commit_msg
