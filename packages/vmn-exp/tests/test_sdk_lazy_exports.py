"""The registry names in ``vmn_exp.sdk.__all__`` resolve on first use (plan 41 D2)."""
import pytest

import vmn_exp.sdk as sdk


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
