"""Assert the installed vmn distribution contains everything the source tree has.

Runs inside a clean-room container with the source mounted read-only at /src.
Must be run from outside /src so imports resolve to the install, never to the
checkout.
"""
import importlib
import os
import sys

SRC_ROOT = "/src"
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

# package_data is easy to declare and easy to forget; verify it landed.
import version_stamp.ui  # noqa: E402

installed_static = os.path.join(os.path.dirname(version_stamp.ui.__file__), "static")
source_static = os.path.join(PKG_ROOT, "ui", "static")
if os.path.isdir(source_static) and os.listdir(source_static):
    if not os.path.isdir(installed_static) or not os.listdir(installed_static):
        problems.append(
            "version_stamp/ui/static: package_data missing from the install"
        )

if problems:
    sys.exit("Installed distribution is incomplete:\n  " + "\n  ".join(problems))

print("OK: every source subpackage and package_data file is present in the install")
