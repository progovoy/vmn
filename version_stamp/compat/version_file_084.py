"""Compatibility with vmn 0.8.4 version file format.

The 0.8.4 ``last_known_app_version.yml`` stored prerelease info as separate
``prerelease`` and ``prerelease_count`` fields alongside ``version_to_stamp_from``.
Even older versions used a ``last_stamped_version`` key.

Safe to remove when: no user has a ``.vmn/*/last_known_app_version.yml`` in
the old format (i.e., after one full stamp cycle on every managed app).
"""


def read_version_from_old_file(ver_dict, serialize_fn, hide_zero_hotfix):
    """Extract version string from an old-format version file dict.

    Handles two legacy layouts:
    1. ``version_to_stamp_from`` + ``prerelease`` + ``prerelease_count`` (0.8.4)
    2. ``last_stamped_version`` (pre-0.8.4)

    Returns the resolved version string, or None if the dict uses the current format.
    """
    if "version_to_stamp_from" in ver_dict:
        verstr = ver_dict["version_to_stamp_from"]
        if "prerelease" in ver_dict:
            base_verstr = verstr
            prerelease = None
            if ver_dict["prerelease"] != "release":
                prerelease = (
                    f"{ver_dict['prerelease']}"
                    f"{ver_dict['prerelease_count'][ver_dict['prerelease']]}"
                )
            verstr = serialize_fn(
                base_verstr,
                prerelease=prerelease,
                hide_zero_hotfix=hide_zero_hotfix,
            )
            return verstr
        return None
    elif "last_stamped_version" in ver_dict:
        return ver_dict["last_stamped_version"]
    return None
