"""Compatibility with old default version template.

The old default template ``[{major}][.{minor}][.{patch}][.{hotfix}][-{prerelease}][+{buildmetadata}]``
lacked ``rcn`` and ``dev`` fields. When detected, it is silently replaced with
the current default.

Safe to remove when: all conf.yml files have been re-saved (any stamp cycle updates them).
"""
from version_stamp.core.constants import VMN_OLD_TEMPLATE
from version_stamp.core.logging import VMN_LOGGER


def migrate_old_template(template, new_default_template):
    """Return ``new_default_template`` if ``template`` matches the old default, else return it unchanged."""
    if template == VMN_OLD_TEMPLATE:
        VMN_LOGGER.warning(
            "Identified old default template format. "
            "will ignore and use the new default format"
        )
        return new_default_template
    return template
