"""The writer id of an adopted SDK run's own stream (plan 38 A5)."""
from vmn_exp.core.streams import GUEST_WRITER_SUFFIX, guest_writer_id


def test_guest_writer_id_keeps_the_writer_as_prefix_and_adds_the_suffix():
    assert GUEST_WRITER_SUFFIX == "-sdk"
    assert guest_writer_id("host-1") == "host-1-sdk"


def test_guest_writer_id_replaces_a_tilde():
    assert guest_writer_id("pod~a") == "pod-a-sdk"
