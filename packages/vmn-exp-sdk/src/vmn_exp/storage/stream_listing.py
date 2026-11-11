"""One remote listing of a record's streams, taken when first needed."""


class StreamListing:
    """``{stream: [objects]}`` from *fetch* (a zero-argument callable), fetched
    on the first :meth:`objects` call and again after :meth:`refresh`."""

    def __init__(self, fetch):
        self._fetch, self._groups = fetch, None

    def objects(self, stream):
        if self._groups is None:
            self._groups = self._fetch()
        return self._groups.get(stream, [])

    def refresh(self):
        self._groups = None
