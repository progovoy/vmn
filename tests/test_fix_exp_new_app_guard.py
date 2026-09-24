"""`vmn exp create`/`vmn exp run` typo guard.

Auto-init on the very first app in a repo is documented, intentional UX (see
`test_exp_ux.py`). But once at least one app already exists, a name that
doesn't match any of them is far more likely a typo (`vmn exp my_ap` for
`my_app`) than a deliberate new app — and unlike `vmn show`/`vmn goto`, `vmn
exp create` silently commits, tags and pushes a brand-new app as a side
effect. These pin that a second, unknown app name is refused by default (with
a hint at the existing app name and the `--new-app` opt-in) while a genuinely
first-ever app keeps auto-initializing exactly as before.
"""
import os

import git

from helpers import _bootstrap, _exp


def _tags(app_layout):
    return {t.name for t in git.Repo(app_layout.repo_path).tags}


def _app_dir(app_layout, name):
    return os.path.join(app_layout.repo_path, ".vmn", name)


def test_typo_app_name_is_refused_when_another_app_exists(app_layout, capfd):
    _bootstrap(app_layout)  # creates + stamps app_layout.app_name ("test_app")

    tags_before = _tags(app_layout)

    capfd.readouterr()
    err = _exp("test_ap", note="typo")  # missing the second "p"
    out, stderr = capfd.readouterr()
    combined = out + stderr

    assert err != 0
    assert "[ERROR]" in combined
    assert app_layout.app_name in combined
    assert "--new-app" in combined

    # No commit/tag/push side effect from the refused attempt.
    assert _tags(app_layout) == tags_before
    assert not os.path.isdir(_app_dir(app_layout, "test_ap"))


def test_typo_app_name_with_new_app_flag_creates_it(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    err = _exp("test_ap", note="genuinely a new app", extra_args=["--new-app"])

    assert err == 0
    assert os.path.isdir(_app_dir(app_layout, "test_ap"))


def test_first_ever_app_still_auto_inits_without_new_app_flag(app_layout, capfd):
    # No other app exists yet in this repo -- must behave exactly as
    # documented (silent cold start), with no mention of the new flag.
    capfd.readouterr()
    err = _exp(app_layout.app_name, note="first ever")
    out, stderr = capfd.readouterr()

    assert err == 0
    assert "--new-app" not in (out + stderr)
    assert os.path.isdir(_app_dir(app_layout, app_layout.app_name))


def test_existing_app_name_is_unaffected(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    err = _exp(app_layout.app_name, note="normal use of the real app")
    out, stderr = capfd.readouterr()

    assert err == 0
    assert "--new-app" not in (out + stderr)
