"""scikit-learn discovery must not import the libraries sklearn vendors shims for.

``sklearn.utils.all_estimators()`` walks every sklearn package with
``pkgutil.walk_packages``, which imports each package to recurse into it. Under
``sklearn.externals.array_api_compat`` sit shims such as ``...torch`` whose
``__init__`` imports torch itself, so a plain ``autolog()`` imported torch —
seconds of import time and, on macOS, a second OpenMP runtime that later
crashed LightGBM's and xgboost's fits in the same process.

The fakes here stand in for sklearn's package tree; a recording finder stands in
for the vendored shim, so the test sees whether discovery tried to import it.
"""
import importlib
import importlib.abc
import importlib.machinery
import sys
import threading
import types

import pytest

from vmn_exp.sdk.autolog_sklearn import _discover_sklearn

SHIM = "sklearn.externals.array_api_compat.torch"


class FakeBaseEstimator:
    def fit(self, X, y=None):
        return self


class FakeRidge(FakeBaseEstimator):
    def fit(self, X, y=None):
        return self


class RecordingFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves *SHIM* as an empty module and remembers being asked for it."""

    def __init__(self):
        self.asked = []

    def find_spec(self, name, path=None, target=None):
        if name != SHIM:
            return None
        self.asked.append(name)
        return importlib.machinery.ModuleSpec(name, self)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        pass


def _package(name):
    module = types.ModuleType(name)
    module.__path__ = []
    return module


def _walking_all_estimators():
    """Like the real helper: import every package on the way, ignore failures."""
    try:
        importlib.import_module(SHIM)
    except ImportError:
        pass
    return [("FakeRidge", FakeRidge)]


@pytest.fixture
def fake_sklearn(monkeypatch):
    sklearn = _package("sklearn")
    base = types.ModuleType("sklearn.base")
    base.BaseEstimator = FakeBaseEstimator
    utils = types.ModuleType("sklearn.utils")
    utils.all_estimators = _walking_all_estimators
    modules = {
        "sklearn": sklearn,
        "sklearn.base": base,
        "sklearn.utils": utils,
        "sklearn.externals": _package("sklearn.externals"),
        "sklearn.externals.array_api_compat": _package(
            "sklearn.externals.array_api_compat"
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, SHIM, raising=False)
    finder = RecordingFinder()
    monkeypatch.setattr(sys, "meta_path", sys.meta_path + [finder])
    yield sklearn, finder
    sys.modules.pop(SHIM, None)


def test_discovery_does_not_import_the_vendored_externals(fake_sklearn):
    sklearn, finder = fake_sklearn

    targets = _discover_sklearn(sklearn)

    assert finder.asked == []
    assert SHIM not in sys.modules
    assert targets == [(FakeRidge, "fit")]


def test_sklearn_own_vendored_modules_still_import_during_discovery(
    fake_sklearn, monkeypatch
):
    """sklearn imports ``sklearn.externals._arff`` from a module the walk loads."""
    sklearn, finder = fake_sklearn
    own = "sklearn.externals._arff"
    monkeypatch.setattr(finder, "find_spec", _serving(own, finder))
    monkeypatch.delitem(sys.modules, own, raising=False)
    imported = []

    def all_estimators():
        imported.append(importlib.import_module(own).__name__)
        return []

    monkeypatch.setattr(sys.modules["sklearn.utils"], "all_estimators", all_estimators)

    _discover_sklearn(sklearn)

    assert imported == [own]
    sys.modules.pop(own, None)


def test_another_thread_imports_the_shim_normally_during_discovery(
    fake_sklearn, monkeypatch
):
    """The refusal is the walk's alone; a training thread importing torch is not refused."""
    sklearn, finder = fake_sklearn
    outcome = []

    def import_elsewhere():
        try:
            outcome.append(importlib.import_module(SHIM).__name__)
        except ImportError as error:
            outcome.append(error)

    def all_estimators():
        worker = threading.Thread(target=import_elsewhere)
        worker.start()
        worker.join()
        return []

    monkeypatch.setattr(sys.modules["sklearn.utils"], "all_estimators", all_estimators)

    _discover_sklearn(sklearn)

    assert outcome == [SHIM]


def _serving(name, loader):
    def find_spec(fullname, path=None, target=None):
        if fullname != name:
            return None
        return importlib.machinery.ModuleSpec(fullname, loader)

    return find_spec


def test_the_vendored_externals_import_normally_after_discovery(fake_sklearn):
    sklearn, finder = fake_sklearn

    _discover_sklearn(sklearn)
    importlib.import_module(SHIM)

    assert finder.asked == [SHIM]
