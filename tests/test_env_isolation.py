"""The autouse env guard in conftest stops VMN_* state leaking between tests.

`version_stamp/cli/entry.py` assigns to ``os.environ["VMN_WRITER_ID"]``, so a
leak here is not only a test's fault - and ``monkeypatch.delenv`` on such a
value makes monkeypatch *restore* it at teardown, leaking it forward into every
later test. These two tests must run in order: the first dirties the
environment, the second asserts it was cleaned.
"""
import os

from version_stamp.core import experiment_writer

PROBE = "VMN_LEAK_PROBE"


def test_a_dirties_vmn_env_and_the_writer_id_cache():
    assert PROBE not in os.environ
    os.environ[PROBE] = "leaked"
    experiment_writer._WRITER_ID = "my-pod"


def test_b_sees_a_clean_environment():
    assert PROBE not in os.environ
    assert experiment_writer._WRITER_ID is None
