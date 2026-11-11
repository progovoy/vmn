"""A conformance kit for storage backends (``vmn_exp.storage`` plugins).

Run it from your own tests against a factory of fresh, empty stores::

    from vmn_exp.storage.conformance import check_store

    def test_my_store_conforms(tmp_path):
        failures = [(name, error) for name, error in check_store(make_my_store)
                    if error is not None]
        assert failures == []

Each check in :data:`CHECKS` takes ``make_store`` and raises (an
``AssertionError`` when the store breaks the contract) or returns.

The race check proves atomicity only probabilistically for a real store: a
check-then-save ``create_exclusive`` can pass it by luck. Passing it is
necessary, not sufficient; use a conditional create (``O_EXCL`` mkdir, S3
``If-None-Match: *``, GCS ``if_generation_match=0``, Azure
``overwrite=False``).
"""
import threading

APP = "conformance"
V1 = "1.0.0-dev.abc1234.0000001"
V2 = "1.0.0-dev.abc1234.0000002"
RACERS = 8


def _meta(verstr, **extra):
    return dict({"verstr": verstr, "app": APP, "format_version": 1}, **extra)


def _includes(metadata, expected):
    assert metadata is not None, "the record has no metadata"
    missing = {k: v for k, v in expected.items() if metadata.get(k) != v}
    assert not missing, f"metadata lacks {missing}: {metadata}"


def _as_bytes(data):
    return data.encode("utf-8") if isinstance(data, str) else data


def check_save_load_record_round_trip(make_store):
    store = make_store()
    store.save(APP, V1, _meta(V1), {"working_tree": "diff"})
    metadata, patches = store.load_record(APP, V1)
    _includes(metadata, _meta(V1))
    assert patches.get("working_tree") == "diff", f"patches came back as {patches}"
    assert store.load_record(APP, V2) == (None, None), "a missing record loads"


def check_metadata_makes_a_record_exist(make_store):
    store = make_store()
    store.save_file(APP, V1, "run_state.yml", b"state: running\n")
    assert not store.exists(APP, V1), "a record without metadata.yml exists"
    assert store.list_snapshots(APP) == [], "a record without metadata.yml is listed"


def check_create_exclusive_claims_once(make_store):
    store = make_store()
    assert store.create_exclusive(APP, V1, _meta(V1), {}) is True, "a free name was refused"
    assert store.create_exclusive(APP, V1, _meta(V1, writer=2), {}) is False, (
        "a taken name was claimed again"
    )
    _includes(store.load_metadata(APP, V1), _meta(V1))


def check_racing_claims_get_exactly_one_win(make_store):
    store = make_store()
    wins, start = [], threading.Barrier(RACERS)

    def claim(i):
        start.wait()
        if store.create_exclusive(APP, V1, _meta(V1, writer=i), {}):
            wins.append(i)

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(RACERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(wins) == 1, f"{len(wins)} of {RACERS} racing writers claimed one name"
    _includes(store.load_metadata(APP, V1), {"writer": wins[0]})


def check_delete_hides_the_record(make_store):
    store = make_store()
    store.create_exclusive(APP, V1, _meta(V1), {})
    store.delete(APP, V1)
    assert not store.exists(APP, V1), "a deleted record exists"
    assert store.list_snapshots(APP) == [], "a deleted record is listed"


def check_file_round_trip(make_store):
    store = make_store()
    store.create_exclusive(APP, V1, _meta(V1), {})
    store.save_file(APP, V1, "notes/a.txt", b"bytes\x00here")
    assert _as_bytes(store.load_file(APP, V1, "notes/a.txt")) == b"bytes\x00here"
    assert store.load_file(APP, V1, "missing.txt") is None, "a missing file loads"


def check_update_metadata_keeps_other_keys(make_store):
    store = make_store()
    store.create_exclusive(APP, V1, _meta(V1, kept="yes"), {})
    assert store.update_metadata(APP, V1, {"note": "hi"}), "the update was refused"
    _includes(store.load_metadata(APP, V1), _meta(V1, kept="yes", note="hi"))
    assert not store.update_metadata(APP, V2, {"note": "x"}), "a missing record was updated"


def check_list_apps(make_store):
    store = make_store()
    store.create_exclusive(APP, V1, _meta(V1), {})
    assert store.list_apps() == [APP], f"list_apps() is {store.list_apps()}"


CHECKS = (
    check_save_load_record_round_trip,
    check_metadata_makes_a_record_exist,
    check_create_exclusive_claims_once,
    check_racing_claims_get_exactly_one_win,
    check_delete_hides_the_record,
    check_file_round_trip,
    check_update_metadata_keeps_other_keys,
    check_list_apps,
)


def _error_of(check, make_store):
    try:
        check(make_store)
    except Exception as error:  # noqa: BLE001 - every failure is the report
        return error
    return None


def check_store(make_store):
    """``[(check name, its error or None)]`` for every check in :data:`CHECKS`."""
    return [(check.__name__, _error_of(check, make_store)) for check in CHECKS]
