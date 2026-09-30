"""Tell a source checkout of vmn apart from an installed release."""
import os

import version_stamp
from version_stamp import version as version_mod

_PACKAGE_DIR = os.path.dirname(os.path.abspath(version_stamp.__file__))


def is_dev_build(package_dir=_PACKAGE_DIR):
    # packages/vmn/src/version_stamp -> packages/vmn/pyproject.toml; a wheel
    # installs version_stamp into site-packages, which has no pyproject.toml.
    project_dir = os.path.dirname(os.path.dirname(package_dir))
    return os.path.isfile(os.path.join(project_dir, "pyproject.toml"))


def display_version():
    if is_dev_build():
        return f"{version_mod.version}+dev"

    return version_mod.version
