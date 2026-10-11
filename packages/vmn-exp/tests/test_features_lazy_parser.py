"""``import vmn_exp.sdk`` leaves the patch parser (vmn_exp.core.features_patch)
unimported: ``features_from_patches`` imports it on first use."""
import subprocess
import sys

_SCRIPT = """\
import sys
import vmn_exp.sdk
from vmn_exp.core.features import features_from_patches
print("vmn_exp.core.features_patch" in sys.modules)
features_from_patches(["diff --git a/x.py b/x.py\\n"])
print("vmn_exp.core.features_patch" in sys.modules)
"""


def test_the_sdk_imports_the_patch_parser_only_when_features_are_parsed():
    result = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["False", "True"]
