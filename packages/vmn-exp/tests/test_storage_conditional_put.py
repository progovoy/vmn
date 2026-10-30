"""``save_file_if_match``: a file write that hands back the stored version's
token (S3 ETag, GCS generation, Azure ETag) and, given the token of the last
write, lands only while nobody wrote the file since.

A local dir's token is its content's hash: a heartbeat on the token of its
own last write is one locked read, no parse.
"""
from test_storage_object_stores import _meta, store  # noqa: F401 (fixture)

from vmn_exp.storage.local import LocalSnapshotStorage

APP = "trainer"
V1 = "1.2.0-dev.abc1234.0000001"
NAME = "run_state.yml"


def _claimed(storage):
    assert storage.create_exclusive(APP, V1, _meta(V1), {})
    return storage


def test_an_unconditional_write_returns_a_token(store):  # noqa: F811
    _claimed(store)
    written, token = store.save_file_if_match(APP, V1, NAME, "a: 1\n")
    assert written and token
    assert store.load_file(APP, V1, NAME) == b"a: 1\n"


def test_a_write_under_the_last_token_lands_and_returns_the_next(store):  # noqa: F811
    _claimed(store)
    _, first = store.save_file_if_match(APP, V1, NAME, "a: 1\n")
    written, second = store.save_file_if_match(APP, V1, NAME, "a: 2\n", first)
    assert written and second and second != first
    written, third = store.save_file_if_match(APP, V1, NAME, "a: 3\n", second)
    assert written and third not in (first, second)
    assert store.load_file(APP, V1, NAME) == b"a: 3\n"


def test_a_write_under_a_stale_token_is_refused(store):  # noqa: F811
    _claimed(store)
    _, mine = store.save_file_if_match(APP, V1, NAME, "a: 1\n")
    store.save_file(APP, V1, NAME, "other: 1\n")
    assert store.save_file_if_match(APP, V1, NAME, "a: 2\n", mine) == (False, None)
    assert store.load_file(APP, V1, NAME) == b"other: 1\n"


def test_a_local_store_returns_the_token_of_its_write(tmp_path):
    storage = _claimed(LocalSnapshotStorage(str(tmp_path)))
    written, token = storage.save_file_if_match(APP, V1, NAME, "a: 1\n")
    assert written and token == storage.load_file_with_token(APP, V1, NAME)[1]
    assert storage.save_file_if_match(APP, V1, NAME, "a: 2\n", token)[0]
    assert storage.load_file(APP, V1, NAME) == b"a: 2\n"
