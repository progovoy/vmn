"""StreamListing: one remote listing of a record's streams, taken when first needed."""
from vmn_exp.storage.stream_listing import StreamListing


class CountingFetch:
    def __init__(self, groups):
        self.groups, self.calls = groups, 0

    def __call__(self):
        self.calls += 1
        return self.groups


def test_fetches_once_until_refreshed():
    fetch = CountingFetch({"w1": ["a", "b"], "w2": ["c"]})
    listing = StreamListing(fetch)

    assert fetch.calls == 0
    assert listing.objects("w1") == ["a", "b"]
    assert listing.objects("w2") == ["c"]
    assert fetch.calls == 1


def test_unknown_stream_is_an_empty_list():
    assert StreamListing(CountingFetch({"w1": ["a"]})).objects("other") == []


def test_refresh_makes_the_next_objects_call_fetch_again():
    fetch = CountingFetch({"w1": ["a"]})
    listing = StreamListing(fetch)
    listing.objects("w1")

    listing.refresh()
    assert fetch.calls == 1
    fetch.groups = {"w1": ["a", "b"]}
    assert listing.objects("w1") == ["a", "b"]
    assert fetch.calls == 2
