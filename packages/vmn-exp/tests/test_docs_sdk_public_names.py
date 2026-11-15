"""docs/vmn-exp/sdk.md's "Public names in `vmn_exp.sdk`" list is exactly
``vmn_exp.sdk.__all__`` (plan 41 D4)."""
import os
import re

import vmn_exp.sdk
from exp_helpers import _PROJECT_ROOT

START = "Public names in `vmn_exp.sdk`:"
END = "Readers live in"


def public_names(markdown_text):
    """The backticked identifiers between START and END in *markdown_text*."""
    start = markdown_text.find(START)
    end = markdown_text.find(END, start)
    assert start >= 0 and end >= 0, (
        f"sdk.md must keep the anchor phrases {START!r} and {END!r}"
    )
    return set(re.findall(r"`(\w+)`", markdown_text[start + len(START) : end]))


def test_public_names_extracts_the_backticked_list():
    text = (
        "Intro `ignored`.\n\n"
        "Public names in `vmn_exp.sdk`: `start_run`, `Run`, and the\n"
        "registry functions `set_alias`, `use_model`. Readers live in\n"
        "`vmn_exp.sdk.reader`."
    )
    assert public_names(text) == {"start_run", "Run", "set_alias", "use_model"}


def _sdk_md():
    path = os.path.join(_PROJECT_ROOT, "docs", "vmn-exp", "sdk.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_sdk_md_public_names_equal_dunder_all():
    documented = public_names(_sdk_md())
    exported = set(vmn_exp.sdk.__all__)
    assert documented == exported, {
        "missing from sdk.md": sorted(exported - documented),
        "not in __all__": sorted(documented - exported),
    }


def test_sdk_md_does_not_send_users_to_core_storage_resolve():
    text = _sdk_md()
    assert "vmn_exp.core.storage_resolve" not in text
    assert "vmn_exp.sdk.resolve_storage" in text
