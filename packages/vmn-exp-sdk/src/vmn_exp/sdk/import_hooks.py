"""Run a callback right after a top-level module is first imported.

``autolog()`` must not import TensorFlow, torch and friends just to patch them:
a sklearn-only script would pay seconds and hundreds of megabytes for libraries
it never uses. Frameworks already in ``sys.modules`` are patched on the spot;
for the rest a meta-path finder waits for the import the user eventually makes
and patches the module the moment its ``__init__`` has finished executing.

The finder only wraps the loader of a module it was asked to watch, restores the
real loader on the module before running it, and never lets a callback failure
break the import.
"""
import importlib.abc
import logging
import sys
import threading

_LOGGER = logging.getLogger(__name__)


class _Loader(importlib.abc.Loader):
    """Delegates to the real loader, then fires the callback."""

    def __init__(self, loader, name, finder):
        self._loader = loader
        self._name = name
        self._finder = finder

    def create_module(self, spec):
        create = getattr(self._loader, "create_module", None)
        return create(spec) if create else None

    def exec_module(self, module):
        # The module sees its real loader, never this wrapper.
        module.__loader__ = self._loader
        if getattr(module, "__spec__", None) is not None:
            module.__spec__.loader = self._loader
        self._loader.exec_module(module)
        self._finder._fire(self._name, module)

    def __getattr__(self, attr):
        return getattr(self._loader, attr)


class _PostImportFinder(importlib.abc.MetaPathFinder):
    def __init__(self):
        self._callbacks = {}
        self._lock = threading.RLock()
        self._local = threading.local()

    def watch(self, name, callback):
        with self._lock:
            self._callbacks[name] = callback
            if self not in sys.meta_path:
                sys.meta_path.insert(0, self)

    def clear(self):
        with self._lock:
            self._callbacks.clear()
            self._detach()

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self._callbacks or getattr(self._local, "busy", False):
            return None
        self._local.busy = True
        try:
            spec = _real_spec(self, fullname, path, target)
        finally:
            self._local.busy = False
        if spec is None or spec.loader is None:
            return spec
        spec.loader = _Loader(spec.loader, fullname, self)
        return spec

    def _fire(self, name, module):
        with self._lock:
            callback = self._callbacks.pop(name, None)
            if not self._callbacks:
                self._detach()
        if callback is None:
            return
        try:
            callback(module)
        except Exception:
            _LOGGER.debug("post-import hook for %s failed", name, exc_info=True)

    def _detach(self):
        if self in sys.meta_path:
            sys.meta_path.remove(self)


def _real_spec(finder, fullname, path, target):
    for other in list(sys.meta_path):
        if other is finder:
            continue
        find = getattr(other, "find_spec", None)
        if find is None:
            continue
        spec = find(fullname, path, target)
        if spec is not None:
            return spec
    return None


_FINDER = _PostImportFinder()


def when_imported(name, callback):
    """Call ``callback(module)`` once, right after *name* is first imported."""
    _FINDER.watch(name, callback)


def clear():
    """Forget every pending hook and detach the finder."""
    _FINDER.clear()
