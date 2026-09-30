"""Make ``vmn_exp`` unimportable in this process, as if vmn-exp were not installed.

The core suite runs with it (tests/conftest.py) so no core test can lean on
vmn-exp by accident, even in a venv that has it installed.
"""
import importlib.abc
import sys


class VmnExpBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "vmn_exp":
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None


def block():
    if not any(isinstance(f, VmnExpBlocker) for f in sys.meta_path):
        sys.meta_path.insert(0, VmnExpBlocker())


def unblock():
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, VmnExpBlocker)]
