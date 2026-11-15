"""With no store at all, open_storage's error names the preferred VMN_STORE."""
import pytest

from vmn_exp.storage.open import open_storage


def test_no_store_and_no_root_names_vmn_store():
    with pytest.raises(ValueError, match="VMN_STORE ") as info:
        open_storage(None, None, clock=None, env={})
    assert "VMN_EXPERIMENT_DIR" in str(info.value)
