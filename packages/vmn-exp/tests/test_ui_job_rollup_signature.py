"""Plan 23 S1/S3: a failed or stuck run's failure signature — the same cause
gives the same short string whatever numbers, paths or ids it mentions."""
import pytest
from vmn_exp.ui.failure_signature import label, signature


def _failed(**fields):
    return dict({"status": "failed", "exit_code": 1}, **fields)


def test_runs_that_did_not_fail_have_no_signature():
    for status in ("succeeded", "running", "created", None):
        assert signature({"status": status, "exit_code": 0, "error_summary": "x"}) is None


def test_numbers_in_the_message_are_masked():
    a = _failed(error_summary="RuntimeError: CUDA out of memory. Tried to allocate 2.31 GiB")
    b = _failed(error_summary="RuntimeError: CUDA out of memory. Tried to allocate 1.07 GiB")
    assert signature(a) == signature(b)
    assert "2.31" not in signature(a)


@pytest.mark.parametrize("one,other", [
    ("FileNotFoundError: /data/shard-0017/part.bin", "FileNotFoundError: /scratch/x/y.bin"),
    ("bad checkpoint 0xdeadbeef", "bad checkpoint 0x1f2e"),
    ("hash mismatch 3f9a2c7be81d", "hash mismatch 00aa11bb22cc"),
    ("run 1.0.0-dev.r000123 died", "run 2.4.1-dev.abc1234.x9 died"),
    ("job 123e4567-e89b-12d3-a456-426614174000 lost", "job 00000000-0000-0000-0000-000000000000 lost"),
    ("rank 3 of 8 timed out after 1e-4s", "rank 12 of 64 timed out after 30.5s"),
])
def test_paths_hex_ids_and_numbers_are_masked(one, other):
    assert signature(_failed(error_summary=one)) == signature(_failed(error_summary=other))


def test_different_causes_differ():
    oom = signature(_failed(error_summary="CUDA out of memory"))
    nan = signature(_failed(error_summary="ValueError: loss is NaN"))
    killed = signature(_failed(exit_code=137, signal="SIGKILL"))
    assert len({oom, nan, killed}) == 3


def test_exit_code_signal_and_end_reason_take_part():
    assert signature(_failed(exit_code=1)) != signature(_failed(exit_code=2))
    assert signature(_failed(signal="SIGTERM")) != signature(_failed(signal="SIGKILL"))
    assert signature(_failed(end_reason="timeout")) != signature(_failed())


def test_a_stuck_run_has_its_own_signature():
    stuck = signature({"status": "stuck", "exit_code": None})
    assert stuck and stuck != signature(_failed(exit_code=None))


def test_signatures_are_short_and_whitespace_insensitive():
    long = _failed(error_summary="Error:\n   " + "word " * 500)
    assert len(signature(long)) <= 200
    assert signature(_failed(error_summary="a  b\n c")) == signature(_failed(error_summary="a b c"))


def test_labels_read_as_text():
    assert "out of memory" in label(signature(_failed(
        error_summary="CUDA out of memory. Tried to allocate 2.31 GiB")))
    assert "SIGKILL" in label(signature(_failed(exit_code=137, signal="SIGKILL")))
    assert "exit 2" in label(signature(_failed(exit_code=2)))
    assert "stuck" in label(signature({"status": "stuck"})).lower()
    assert label(None) is None
