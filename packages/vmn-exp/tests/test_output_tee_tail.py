"""The stderr tail the tee keeps for parsing a run's error."""
from vmn_exp.cli.output_tee import TailBuffer


def test_the_tail_buffer_keeps_only_the_end():
    tail = TailBuffer(10)
    for chunk in (b"head-noise ", b"0123456789", b"abcdef"):
        tail.write(chunk)
    assert tail.text() == "6789abcdef"


def test_the_tail_buffer_decodes_undecodable_bytes():
    tail = TailBuffer(64)
    tail.write(b"bad \xff byte")
    assert tail.text() == "bad � byte"
