"""The argv of each ui mutation action: request body -> ``vmn``/``vmn-exp`` command.

Pure: nothing here runs a command; :mod:`vmn_exp.ui.jobs` runs them.
"""
from vmn_exp.ui.job_argv import ACTIONS, opt, positional, switch
from vmn_exp.ui.jobs_exp_meta import (
    _valid_verstr,
    exp_add_command,
    exp_archive_command,
    exp_create_command,
    exp_note_command,
    exp_prune_command,
    exp_push_command,
    exp_restore_command,
    exp_rewind_command,
    exp_tag_command,
)

_RELEASE_MODES = ("major", "minor", "patch", "hotfix")


def _version_args(body):
    """``--version=<verstr>``, or nothing for a missing or empty verstr."""
    verstr = body.get("verstr")
    if verstr is None or verstr == "":
        return [], None
    if not _valid_verstr(verstr):
        return None, "A valid verstr is required"
    return [opt("--version", verstr)], None


def _stamp_command(app_name, body):
    mode, prerelease = body.get("release_mode"), body.get("prerelease")
    if mode not in _RELEASE_MODES:
        return None, "release_mode must be major|minor|patch|hotfix"
    cmd = ["vmn", "stamp", opt("--release-mode", mode)]
    if prerelease:
        if not isinstance(prerelease, str) or not prerelease.isprintable():
            return None, "prerelease must be a printable string"
        cmd.append(opt("--pr", prerelease))
    if body.get("dry_run"):
        cmd.append(switch("--dry-run"))
    return cmd + [positional(app_name)], None


def _core_version_command(verb):
    """``vmn release|goto [--version=<verstr>] <app>``."""
    def build(app_name, body):
        args, err = _version_args(body)
        if err:
            return None, err
        return ["vmn", verb, *args, positional(app_name)], None

    return build


def _exp_archive(verb):
    return lambda app_name, body: exp_archive_command(verb, app_name, body)


_BUILDERS = {
    "stamp": _stamp_command,
    "release": _core_version_command("release"),
    "goto": _core_version_command("goto"),
    "restore": exp_restore_command,
    "prune": exp_prune_command,
    "exp_create": exp_create_command,
    "exp_add": exp_add_command,
    "note": exp_note_command,
    "exp_tag": exp_tag_command,
    "exp_rewind": exp_rewind_command,
    "exp_push": exp_push_command,
    "exp_archive": _exp_archive("archive"),
    "exp_unarchive": _exp_archive("unarchive"),
}


def build_command(action, app_name, body):
    """Translate an action + request body into a ``vmn``/``vmn-exp`` argv list.

    Returns (argv, error_message_or_None). Kept pure for testing/preview.
    """
    if action not in ACTIONS:
        return None, f"Unknown action '{action}'"
    try:
        return _BUILDERS[action](app_name, body or {})
    except ValueError as e:
        return None, str(e)
