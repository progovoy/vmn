"""The code verstr code-less runs share is a run verstr like any other: it
takes the ``.rN`` and the writer-id suffix and is claimed exclusively (plan 38
A10 spike)."""
from memory_storage import MemoryStorage
from vmn_exp._base import valid_path_component
from vmn_exp.core import run_hint
from vmn_exp.core.writer import allocate_run_verstr, check_run_id, record_maker
from vmn_exp.sdk.codeless import CODELESS_VERSTR


def _allocate(storage, suffix=None):
    make = record_maker({"app_name": "app"}, CODELESS_VERSTR)
    return allocate_run_verstr(storage, "app", CODELESS_VERSTR, make_record=make, suffix=suffix)


def test_the_codeless_code_verstr_parses_as_a_run_verstr_and_takes_the_r_suffix():
    run_hint.clear()
    assert valid_path_component(CODELESS_VERSTR)
    assert "-dev." not in CODELESS_VERSTR
    assert run_hint.run_number(CODELESS_VERSTR, run_hint.run_name(CODELESS_VERSTR, 3)) == 3
    storage = MemoryStorage()
    assert [_allocate(storage) for _ in range(3)] == [
        CODELESS_VERSTR, f"{CODELESS_VERSTR}.r2", f"{CODELESS_VERSTR}.r3"]


def test_it_takes_a_writer_id_suffix():
    storage = MemoryStorage()
    first, second = _allocate(storage, "pod-7"), _allocate(storage, "pod-7")
    assert (first, second) == (f"{CODELESS_VERSTR}.pod-7", f"{CODELESS_VERSTR}.pod-7.2")
    check_run_id(CODELESS_VERSTR, first)
    assert storage.metadata[("app", first)]["code_verstr"] == CODELESS_VERSTR
