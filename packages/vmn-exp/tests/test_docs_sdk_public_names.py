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


def test_sdk_md_public_names_equal_dunder_all():
    path = os.path.join(_PROJECT_ROOT, "docs", "vmn-exp", "sdk.md")
    with open(path, encoding="utf-8") as f:
        documented = public_names(f.read())
    exported = set(vmn_exp.sdk.__all__)
    assert documented == exported, {
        "missing from sdk.md": sorted(exported - documented),
        "not in __all__": sorted(documented - exported),
    }
