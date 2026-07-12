#!/usr/bin/env python3
"""Non-interactive config file generation for `vmn config gen`."""
import dataclasses
import os

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.models import AppConf
from version_stamp.cli.config_tui import (
    _get_dep_branch,
    _read_raw_conf,
    _resolve_conf_target,
    _set_dep_pin,
    _write_full_config,
)


def _sync_dep_branches(raw_conf, vmn_root_path):
    """Repin each branch-pinned dep to the branch its repo is currently on."""
    for rel_dir, repos in (raw_conf.get("deps") or {}).items():
        for repo_name, dep_conf in repos.items():
            if not isinstance(dep_conf, dict) or "branch" not in dep_conf:
                continue
            rel_path = os.path.join(rel_dir, repo_name)
            actual = _get_dep_branch(os.path.join(vmn_root_path, rel_path))
            if actual:
                _set_dep_pin(dep_conf, "branch", actual)
            else:
                VMN_LOGGER.warning(
                    f"Could not detect the current branch of dep "
                    f"'{rel_path}'. Keeping branch: {dep_conf['branch']}"
                )


def handle_config_gen(vmn_ctx):
    """Create a config file without any TTY interaction.

    Default target is the app's conf.yml seeded from AppConf() defaults;
    --root seeds an empty root conf; --branch (± --root) targets the canonical
    branch conf seeded from the current effective conf. Never overwrites.
    """
    vcs = vmn_ctx.vcs
    if vcs.name is None:
        VMN_LOGGER.error("config gen requires an application name.")
        return 1

    if vmn_ctx.args.branch:
        conf_path, _, seed_source = _resolve_conf_target(vmn_ctx)
        if conf_path is None:
            return 1
        raw_conf = _read_raw_conf(seed_source)
        if vmn_ctx.args.sync_dep_branches:
            _sync_dep_branches(raw_conf, vcs.vmn_root_path)
    elif vmn_ctx.args.root:
        conf_path, _, _ = _resolve_conf_target(vmn_ctx)
        if conf_path is None:
            return 1
        raw_conf = {"external_services": {}}
    else:
        # Always target the default conf.yml, not the branch-resolved conf.
        conf_path = os.path.join(vcs.app_dir_path, "conf.yml")
        raw_conf = dataclasses.asdict(AppConf())

    if os.path.isfile(conf_path):
        VMN_LOGGER.error(f"Config file already exists: {conf_path}")
        return 1

    _write_full_config(conf_path, raw_conf)
    VMN_LOGGER.info(f"Created config file: {conf_path}")
    return 0
