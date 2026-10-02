from vmn_exp.core.journal_keys import (
    JournalKey,
    decode_key,
    encode_key,
    partition_of,
    partition_prefixes,
)

MS = 1_700_000_000_123  # 2023-11-14 22:13:20 UTC


def _key(**kw):
    base = dict(unix_ms=MS, area="runs", app_key="my_app",
                writer_id="w_1/x", seq=3, name="0.0.1-dev.ab_c/d%e")
    base.update(kw)
    return JournalKey(**base)


def test_layout():
    enc = encode_key(_key())
    assert enc.startswith("journal/202311142213/1700000000123_runs_")
    tail = enc.split("/", 2)[2]
    assert tail.count("_") == 5
    assert "/" not in tail


def test_round_trip_awkward_fields():
    for name in ["a_b", "x/y", "%5F", "é ü", "", "a.b-c~d"]:
        k = _key(name=name, writer_id=name + "w", app_key="root-" + name)
        assert decode_key(encode_key(k)) == k


def test_zero_padded_sorts_by_time():
    early = encode_key(_key(unix_ms=5, name="z"))
    late = encode_key(_key(unix_ms=10, name="a"))
    assert early.split("/")[2] < late.split("/")[2]
    assert early.split("/")[2].startswith("0000000000005_")


def test_decode_rejects_garbage():
    assert decode_key("journal/202311142213/nope") is None
    assert decode_key("journal/202311142213/x_runs_a_w_1_n") is None
    assert decode_key("other/x") is None


def test_partition_of_minute():
    assert partition_of(MS) == "202311142213"
    assert partition_of(MS - 20_124) == "202311142212"


def test_partition_prefixes_span():
    got = partition_prefixes(MS - 120_000, MS)
    assert got == ["journal/202311142211/", "journal/202311142212/",
                   "journal/202311142213/"]
    assert partition_prefixes(MS, MS) == ["journal/202311142213/"]
