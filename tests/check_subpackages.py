"""Assert the installed vmn distribution contains everything the source tree has.

Runs inside a clean-room container with the source mounted read-only at /src.
Must be run from outside /src so imports resolve to the install, never to the
checkout.
"""
import importlib
import os
import sys

SRC_ROOT = "/src/packages/vmn/src"
PKG_ROOT = os.path.join(SRC_ROOT, "version_stamp")

problems = []

for dirpath, _dirnames, filenames in os.walk(PKG_ROOT):
    if "__init__.py" not in filenames:
        continue

    module = os.path.relpath(dirpath, SRC_ROOT).replace(os.sep, ".")
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:
        problems.append("{}: not importable ({})".format(module, exc))
        continue

    origin = getattr(mod, "__file__", "") or ""
    if origin.startswith(SRC_ROOT):
        problems.append(
            "{}: resolved to the source tree, not the install".format(module)
        )

if problems:
    sys.exit("Installed distribution is incomplete:\n  " + "\n  ".join(problems))

print("OK: every source subpackage is present in the install")
