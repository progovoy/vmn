"""Tests for _Adapter.watch= and custom method_owners hook.

Tests:
- test_watch_submodule_patches_on_submodule_import: importing the top-level
  alone does NOT patch; importing the watched submodule DOES.
- test_method_owners_custom_attr: an adapter's method_owners hook wrapping
  'train' records into the current run just like 'fit' does.
- test_default_adapter_unchanged: _adapter() with no extra args produces an
  _Adapter with watch=() and method_owners=None (existing adapters unaffected).
"""
import importlib
import sys
import types

import pytest

from version_stamp.exp import autolog as autolog_fn
from version_stamp.exp import autolog_disable
from version_stamp.exp import run as run_module
from version_stamp.exp.autolog import SUPPORTED_FRAMEWORKS, _PATCH_MARKER
from version_stamp.exp.autolog_adapter import _adapter


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class FakeRun:
    """Minimal run recorder — same interface the real SDK uses."""

    def __init__(self):
        self.param_calls = []
        self.metric_calls = []

    @property
    def params(self):
        merged = {}
        for call in self.param_calls:
            merged.update(call)
        return merged

    @property
    def metrics(self):
        merged = {}
        for call in self.metric_calls:
            merged.update(call)
        return merged

    def log_params(self, mapping):
        self.param_calls.append(dict(mapping))

    def log_metrics(self, mapping, step=None):
        self.metric_calls.append(dict(mapping))

    def log_metric(self, key, value, step=None):
        self.log_metrics({key: value})


@pytest.fixture
def open_run():
    """Push a fake run onto the SDK open-run stack."""
    fake = FakeRun()
    run_module._OPEN_RUNS.append(fake)
    yield fake
    run_module._OPEN_RUNS.remove(fake)


@pytest.fixture(autouse=True)
def restore_autolog():
    """Undo all patches and pending hooks after every test."""
    yield
    autolog_disable()


# ---------------------------------------------------------------------------
# test_watch_submodule_patches_on_submodule_import
# ---------------------------------------------------------------------------


def _build_lazy_package(tmp_path, pkg, submod):
    """Write a real package to tmp_path: pkg/__init__.py does NOT import submod."""
    pkg_dir = tmp_path / pkg
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text(
        "# top-level intentionally does not import the submodule\n"
    )
    (pkg_dir / f"{submod}.py").write_text(
        "class Trainer:\n"
        "    def train(self, data):\n"
        "        return 'trained'\n"
    )


def test_watch_submodule_patches_on_submodule_import(tmp_path):
    """Importing the top-level alone must not patch; importing the submodule must."""
    pkg = "fakepkg_watch_test"
    sub = "trainer"
    full_sub = f"{pkg}.{sub}"

    _build_lazy_package(tmp_path, pkg, sub)
    sys.path.insert(0, str(tmp_path))

    # Guard: remove stale entries from earlier runs
    for name in list(sys.modules):
        if name == pkg or name.startswith(pkg + "."):
            sys.modules.pop(name)

    def _discover(module):
        trainer_cls = getattr(module, "Trainer", None)
        if trainer_cls is None:
            return []
        for klass in trainer_cls.__mro__:
            if "train" in vars(klass):
                return [(klass, "train")]
        return []

    adapter = _adapter("fakepkg", _discover, watch=(full_sub,))
    SUPPORTED_FRAMEWORKS[pkg] = adapter

    try:
        autolog_fn(frameworks=[pkg])

        # Import top-level — must NOT trigger patching (top-level is not watched)
        top = importlib.import_module(pkg)
        assert full_sub not in sys.modules, "submodule must not be imported yet"

        # Import submodule — MUST trigger patching
        submod_obj = importlib.import_module(full_sub)

        trainer_cls = submod_obj.Trainer
        current_train = trainer_cls.__dict__.get("train")
        assert current_train is not None, "Trainer.train disappeared"
        assert getattr(current_train, _PATCH_MARKER, None) is not None, (
            "Trainer.train was not patched after importing the submodule"
        )
    finally:
        SUPPORTED_FRAMEWORKS.pop(pkg, None)
        for name in list(sys.modules):
            if name == pkg or name.startswith(pkg + "."):
                sys.modules.pop(name)
        sys.path.remove(str(tmp_path))


# ---------------------------------------------------------------------------
# test_method_owners_custom_attr
# ---------------------------------------------------------------------------


def test_method_owners_custom_attr(open_run):
    """method_owners hook wrapping 'train' records into current_run like 'fit'."""
    pkg = "_fake_custom_method_pkg"

    class FakeTrainer:
        def train(self, data):
            return "trained"

    fake_module = types.ModuleType(pkg)
    fake_module.FakeTrainer = FakeTrainer
    sys.modules[pkg] = fake_module

    def _method_owners_fn(module):
        cls = getattr(module, "FakeTrainer", None)
        if cls is None:
            return []
        for klass in cls.__mro__:
            if "train" in vars(klass):
                return [(klass, "train")]
        return []

    # discover is not called when method_owners is set; pass a sentinel
    sentinel_discover_called = []

    def _sentinel_discover(module):
        sentinel_discover_called.append(True)
        return []

    adapter = _adapter(
        "fakehf",
        discover=_sentinel_discover,
        method_owners=_method_owners_fn,
    )
    SUPPORTED_FRAMEWORKS[pkg] = adapter

    try:
        autolog_fn(frameworks=[pkg])

        # train must now be patched
        current_train = FakeTrainer.__dict__.get("train")
        assert current_train is not None
        assert getattr(current_train, _PATCH_MARKER, None) is not None, (
            "FakeTrainer.train was not patched"
        )

        # When method_owners is present, discover should not be called
        assert not sentinel_discover_called, "discover should not be called when method_owners is set"

        # Calling train records estimator name in the open run
        FakeTrainer().train([[1.0]])
        assert open_run.params.get("fakehf_estimator") == "FakeTrainer"

        # Return value passes through unmodified
        result = FakeTrainer().train([[2.0]])
        assert result == "trained"
    finally:
        SUPPORTED_FRAMEWORKS.pop(pkg, None)
        sys.modules.pop(pkg, None)


# ---------------------------------------------------------------------------
# test_default_adapter_unchanged
# ---------------------------------------------------------------------------


def test_default_adapter_unchanged():
    """Existing _adapter() calls get watch=() and method_owners=None by default."""
    def dummy_discover(module):
        return []

    a = _adapter("myfw", dummy_discover)
    assert a.watch == ()
    assert a.method_owners is None
    assert a.label == "myfw"
    assert a.discover is dummy_discover
