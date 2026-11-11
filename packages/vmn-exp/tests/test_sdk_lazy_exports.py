"""The registry and reader names and ``resolve_storage`` in
``vmn_exp.sdk.__all__`` resolve on first use (plan 41 D2, D10)."""
import inspect
import os

import pytest

import vmn_exp.sdk as sdk

READER_NAMES = (
    "list_runs",
    "get_run",
    "get_run_state",
    "get_run_states",
    "get_lineage",
    "similar_runs",
    "runs_dataframe",
    "get_metric_history",
    "param_importance",
)


def test_every_name_in_all_resolves():
    missing = [name for name in sdk.__all__ if not callable(getattr(sdk, name, None))]
    assert missing == []


def test_star_import_exposes_registry_functions():
    namespace = {}
    exec("from vmn_exp.sdk import *", namespace)
    from vmn_exp.sdk.models import register_model
    from vmn_exp.sdk.usage import use_dataset

    assert namespace["register_model"] is register_model
    assert namespace["use_dataset"] is use_dataset


def test_dir_lists_the_lazy_names():
    assert {"register_model", "use_model", "get_dataset_version"} <= set(dir(sdk))


def test_unknown_attribute_raises_attribute_error():
    with pytest.raises(AttributeError, match="no_such_name"):
        sdk.no_such_name


def test_resolve_storage_takes_the_six_documented_keywords_only():
    params = inspect.signature(sdk.resolve_storage).parameters
    assert list(params) == ["dir", "store", "bucket", "prefix", "endpoint_url", "repo_root"]
    assert {p.kind for p in params.values()} == {inspect.Parameter.KEYWORD_ONLY}
    assert {p.default for p in params.values()} == {None}


def test_resolve_storage_is_its_own_function():
    from vmn_exp.core.storage_resolve import resolve_experiment_storage

    assert sdk.resolve_storage is not resolve_experiment_storage
    assert sdk.resolve_storage.__module__ == "vmn_exp.sdk.store_resolve"


def test_resolve_storage_with_dir_opens_a_store_under_it(tmp_path, monkeypatch):
    # monkeypatch until plan 44 G12 gives the core resolver an env parameter.
    for key in [k for k in os.environ if k.startswith(("VMN_EXPERIMENT_", "VMN_EXP_"))]:
        monkeypatch.delenv(key)

    sdk.resolve_storage(dir=str(tmp_path), repo_root=False)

    assert (tmp_path / "store.yml").is_file()


def test_reader_names_resolve_to_reader_module_functions():
    from vmn_exp.sdk import reader

    assert set(READER_NAMES) | {"resolve_storage"} <= set(sdk.__all__)
    for name in READER_NAMES:
        assert getattr(sdk, name) is getattr(reader, name), name
