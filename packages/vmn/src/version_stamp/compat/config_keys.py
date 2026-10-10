"""Compatibility for deprecated/renamed configuration keys.

Handles:
1. ``create_verinfo_files`` → ``create_snapshots`` rename
2. ``conventional_commits.default_release_mode`` (nested dict) → top-level ``release_mode_policy``
3. Top-level ``default_release_mode`` with policy values → ``release_mode_policy``
4. ``vmn_version_file`` backend (dropped)

Loading migrates in memory (debug log only); ``vmn stamp`` rewrites the
deprecated keys in the conf file via ``rewrite_deprecated_conf_keys``
(``compat/conf_rewrite.py``).

Safe to remove when: all conf.yml files have gone through at least one stamp
cycle that rewrites them.
"""
from version_stamp.compat.conf_rewrite import POLICY_VALUES, VMN_VERSION_FILE
from version_stamp.core.logging import VMN_LOGGER


def migrate_config_keys(data_conf, app_conf_path):
    """Mutate ``data_conf`` dict in place, migrating deprecated keys.

    Returns whether a key ``rewrite_deprecated_conf_keys`` rewrites on disk
    was found (``create_verinfo_files`` is only migrated in memory).
    """
    _migrate_create_verinfo_files(data_conf, app_conf_path)
    migrated = [
        _migrate_nested_release_mode_policy(data_conf, app_conf_path),
        _migrate_top_level_release_mode_policy(data_conf, app_conf_path),
        _drop_vmn_version_file_backend(data_conf, app_conf_path),
    ]
    return any(migrated)


def _migrate_create_verinfo_files(data_conf, app_conf_path):
    if "create_verinfo_files" in data_conf and "create_snapshots" not in data_conf:
        data_conf["create_snapshots"] = data_conf["create_verinfo_files"]
        VMN_LOGGER.debug(
            "Migrating deprecated config key 'create_verinfo_files' "
            "to 'create_snapshots' in %s. "
            "Remove 'create_verinfo_files' from your conf.yml to silence this.",
            app_conf_path,
        )


def _migrate_nested_release_mode_policy(data_conf, app_conf_path):
    cc = data_conf.get("conventional_commits")
    if isinstance(cc, dict) and "default_release_mode" in cc:
        val = cc.pop("default_release_mode")
        if val in POLICY_VALUES:
            data_conf.setdefault("release_mode_policy", val)
        if not cc:
            data_conf["conventional_commits"] = True
        VMN_LOGGER.debug(
            "Migrating 'conventional_commits.default_release_mode' "
            "to top-level 'release_mode_policy' in %s.",
            app_conf_path,
        )
        return True
    return False


def _migrate_top_level_release_mode_policy(data_conf, app_conf_path):
    drm = data_conf.get("default_release_mode")
    if drm in POLICY_VALUES:
        data_conf.setdefault("release_mode_policy", drm)
        data_conf["default_release_mode"] = ""
        VMN_LOGGER.debug(
            "Migrating top-level 'default_release_mode: %s' "
            "to 'release_mode_policy' in %s.",
            drm,
            app_conf_path,
        )
        return True
    return False


def _drop_vmn_version_file_backend(data_conf, app_conf_path):
    backends = data_conf.get("version_backends")
    if isinstance(backends, dict) and VMN_VERSION_FILE in backends:
        backends.pop(VMN_VERSION_FILE)
        VMN_LOGGER.debug(
            "Dropping the deprecated vmn_version_file version backend in %s.",
            app_conf_path,
        )
        return True
    return False
