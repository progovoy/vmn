"""Compatibility for legacy shell completion scripts.

Old vmn versions installed inline argcomplete eval commands without
managed markers. The new managed-block installer strips these on upgrade.

Safe to remove when: no user has the old inline eval in their shell rc
(i.e., one full ``--completion-install`` cycle).
"""

LEGACY_COMPLETION_SCRIPTS = {
    "bash": 'eval "$(register-python-argcomplete vmn)"',
    "zsh": "autoload -U bashcompinit\nbashcompinit\n"
    'eval "$(register-python-argcomplete vmn)"',
    "fish": "register-python-argcomplete --shell fish vmn | source",
    "tcsh": "eval `register-python-argcomplete --shell tcsh vmn`",
}


def strip_legacy_completion(content, shell):
    """Remove old-style (pre-managed-block) completion from rc file content."""
    from version_stamp.cli.completion import COMPLETION_MARKER

    legacy_block = (
        f"\n{COMPLETION_MARKER}\n"
        f"{LEGACY_COMPLETION_SCRIPTS[shell]}\n"
    )
    return content.replace(legacy_block, "")
