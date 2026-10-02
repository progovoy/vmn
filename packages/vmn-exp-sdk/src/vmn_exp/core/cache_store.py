#!/usr/bin/env python3
"""The persistence interface of :mod:`vmn_exp.core.index` and the UI read cache.

A ``scope`` names one app's records (today the app name; one database per
workspace or store). Every :meth:`CacheStore.save` that changes something bumps
the scope's *generation*, so a follower can catch up with
:meth:`CacheStore.load_since` instead of reloading everything. Implementations
never raise: an unavailable store behaves like an empty one.
"""
from typing import Protocol, runtime_checkable

# ``load_since`` returns this as *removed* when the follower's generation is
# older than the tombstone horizon: *changed* is then the complete record set
# and every key it lacks is gone.
FULL_LOAD = None


@runtime_checkable
class CacheStore(Protocol):
    def load(self, scope) -> dict:
        """``{key: record}`` persisted for *scope*."""

    def save(self, scope, changed, removed, states=None) -> None:
        """Persist *changed*/*states*, forget *removed*; bumps the generation."""

    def generation(self, scope) -> int:
        """Monotonically increasing per scope; 0 before the first save."""

    def load_since(self, scope, generation) -> tuple:
        """``(changed, removed, new_generation)`` after *generation*."""

    def kv_get(self, scope, fingerprint):
        """The payload stored under *scope* if its fingerprint matches, else None."""

    def kv_put(self, scope, fingerprint, payload) -> None:
        """Store a JSON-serializable *payload* under *scope*."""
