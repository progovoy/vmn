from collections.abc import Mapping


class FakeEnv(Mapping):
    """A read-only environment built from a dict."""

    def __init__(self, values=None):
        self._values = dict(values or {})

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)
