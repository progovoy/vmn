"""A git backend asks git for its remote's URL once (plan 39 B9d): the
stamper's init, its deps state and a run record all read ``remote()``, and
each read was a ``git remote get-url --all`` process."""
from version_stamp.backends.git_history import GitHistoryMixin


class RecordingRemote:
    def __init__(self, url):
        self._url = url
        self.url_queries = 0

    @property
    def urls(self):
        self.url_queries += 1
        yield self._url


class Backend(GitHistoryMixin):
    def __init__(self, remote, root="/repo"):
        self.selected_remote = remote
        self._root = root

    def root(self):
        return self._root


def test_remote_asks_for_the_remote_url_once():
    remote = RecordingRemote("https://example.com/repo.git")
    backend = Backend(remote)

    answers = [backend.remote() for _ in range(3)]

    assert answers == ["https://example.com/repo.git"] * 3
    assert remote.url_queries == 1


def test_remote_of_a_backend_without_a_remote_is_none():
    assert Backend(None).remote() is None


def test_each_backend_asks_for_its_own_remote_url():
    first = Backend(RecordingRemote("https://example.com/a.git"))
    second = Backend(RecordingRemote("https://example.com/b.git"))

    assert (first.remote(), second.remote()) == (
        "https://example.com/a.git", "https://example.com/b.git")
