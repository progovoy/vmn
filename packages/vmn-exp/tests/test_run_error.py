"""``core/run_error``: how a failed run's exception is recorded in its run state."""
from vmn_exp.core import run_error
from vmn_exp.core.run_error import (
    MAX_MESSAGE_BYTES,
    error_from_exception,
    error_from_output,
    error_summary,
    slim_run_state,
    state_error_summary,
)


def _raised(exc):
    try:
        raise exc
    except BaseException as caught:
        return caught


class TrainingDiverged(Exception):
    class Inner(Exception):
        pass


# -- error_from_exception ---------------------------------------------------


def test_builtin_exception_type_has_no_module_prefix():
    error = error_from_exception(_raised(RuntimeError("dataloader worker died")))
    assert error["type"] == "RuntimeError"
    assert error["message"] == "dataloader worker died"
    assert error["source"] == "exception"
    assert error["traceback"].startswith("Traceback (most recent call last):")
    assert error["traceback"].rstrip().endswith("RuntimeError: dataloader worker died")


def test_custom_exception_type_is_module_qualified():
    error = error_from_exception(_raised(TrainingDiverged.Inner("nan")))
    assert error["type"] == f"{__name__}.TrainingDiverged.Inner"


def test_exception_without_traceback_still_formats():
    error = error_from_exception(ValueError("never raised"))
    assert error["type"] == "ValueError"
    assert "ValueError: never raised" in error["traceback"]


def test_long_traceback_is_capped_keeping_head_and_tail():
    exc = _raised(ValueError("x" * 100_000))
    tb = error_from_exception(exc)["traceback"]
    assert len(tb.encode()) <= run_error.MAX_TRACEBACK_BYTES
    assert tb.startswith("Traceback (most recent call last):")
    assert tb.endswith("x" * 100)
    assert "bytes elided" in tb


def test_short_traceback_is_kept_whole():
    error = error_from_exception(_raised(KeyError("k")))
    assert "elided" not in error["traceback"]


# -- error_from_output ------------------------------------------------------

_SIMPLE = """\
epoch 1 loss 0.5
Traceback (most recent call last):
  File "train.py", line 3, in <module>
    main()
  File "train.py", line 2, in main
    raise RuntimeError("CUDA out of memory. Tried to allocate 2 GiB")
RuntimeError: CUDA out of memory. Tried to allocate 2 GiB
"""


def test_output_traceback_is_parsed():
    error = error_from_output(_SIMPLE)
    assert error["type"] == "RuntimeError"
    assert error["message"] == "CUDA out of memory. Tried to allocate 2 GiB"
    assert error["source"] == "output"
    assert error["traceback"].startswith("Traceback (most recent call last):")
    assert error["traceback"].endswith("RuntimeError: CUDA out of memory. Tried to allocate 2 GiB")
    assert "epoch 1" not in error["traceback"]
    assert error["output_tail"] == _SIMPLE.rstrip("\n")


def test_chained_traceback_takes_the_last_block():
    text = """\
Traceback (most recent call last):
  File "a.py", line 1, in <module>
KeyError: 'lr'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "a.py", line 3, in <module>
torch.cuda.OutOfMemoryError: CUDA out of memory

rank 1 exiting
"""
    error = error_from_output(text)
    assert error["type"] == "torch.cuda.OutOfMemoryError"
    assert error["message"] == "CUDA out of memory"
    assert "KeyError" not in error["traceback"]


def test_exception_without_message():
    text = """\
Traceback (most recent call last):
  File "a.py", line 1, in <module>
    time.sleep(10)
KeyboardInterrupt
"""
    error = error_from_output(text)
    assert error["type"] == "KeyboardInterrupt"
    assert error["message"] == ""


def test_multiline_message_is_kept():
    text = """\
Traceback (most recent call last):
  File "a.py", line 1, in <module>
ValueError: first line
second line
"""
    error = error_from_output(text)
    assert error["type"] == "ValueError"
    assert error["message"] == "first line\nsecond line"


def test_no_traceback_keeps_only_the_tail():
    assert error_from_output("Killed\n") == {"source": "output", "output_tail": "Killed"}


def test_empty_output_is_no_error():
    assert error_from_output("") is None
    assert error_from_output(None) is None
    assert error_from_output("\n \n") is None


def test_output_tail_is_the_last_50_lines():
    text = "\n".join(f"line {i}" for i in range(200))
    tail = error_from_output(text)["output_tail"].splitlines()
    assert tail[0] == "line 150" and tail[-1] == "line 199"
    assert len(tail) == run_error.OUTPUT_TAIL_LINES


def test_output_tail_is_byte_capped():
    text = "\n".join("y" * 10_000 for _ in range(20))
    tail = error_from_output(text)["output_tail"]
    assert len(tail.encode()) <= run_error.MAX_OUTPUT_TAIL_BYTES
    assert tail.endswith("y" * 100)


# -- error_summary ----------------------------------------------------------


def test_summary_is_type_and_first_message_line():
    assert error_summary({"type": "ValueError", "message": "bad\nmore"}) == "ValueError: bad"


def test_summary_is_type_alone_without_a_message():
    assert error_summary({"type": "KeyboardInterrupt", "message": ""}) == "KeyboardInterrupt"


def test_summary_without_type_is_the_message():
    assert error_summary({"message": "gave up", "source": "user"}) == "gave up"


def test_summary_without_type_falls_back_to_the_last_output_line():
    error = {"source": "output", "output_tail": "step 1\nKilled\n\n"}
    assert error_summary(error) == "Killed"


def test_summary_is_truncated():
    summary = error_summary({"type": "ValueError", "message": "z" * 1000})
    assert len(summary) == run_error.MAX_SUMMARY_CHARS
    assert summary.startswith("ValueError: zzz")


def test_summary_of_nothing_is_none():
    assert error_summary(None) is None
    assert error_summary({}) is None
    assert error_summary("not a mapping") is None
    assert error_summary({"source": "output", "output_tail": ""}) is None


def test_values_are_plain_yaml_types():
    error = error_from_exception(_raised(OSError(2, "missing")))
    assert all(isinstance(v, str) for v in error.values())


def test_traceback_text_is_parsed_instead_of_the_mixed_output():
    # stdout printed before the crash can land after the stderr traceback
    stderr = "Traceback (most recent call last):\n  File \"a.py\", line 2\nValueError: bad lr\n"
    mixed = "Traceback (most recent call last):\n  File \"a.py\", line 2\nValueError: bad lr\nepoch 1\n"
    error = error_from_output(mixed, traceback_text=stderr)
    assert error["type"] == "ValueError"
    assert error["message"] == "bad lr"
    assert "epoch 1" in error["output_tail"]


def test_traceback_text_without_a_traceback_keeps_only_the_tail():
    error = error_from_output("disk full\n", traceback_text="warning: slow\n")
    assert "type" not in error
    assert error["output_tail"] == "disk full"


def test_a_huge_exception_message_is_capped():
    error = error_from_exception(ValueError("x" * 200_000))
    assert len(error["message"].encode()) <= MAX_MESSAGE_BYTES + 100
    assert error["message"].startswith("xxx")


def test_the_slim_run_state_keeps_the_summary_not_the_error():
    state = {"exit_code": 1, "error": {"type": "ValueError", "message": "bad lr", "traceback": "tb"}}
    slim = slim_run_state(state)
    assert "error" not in slim
    assert slim["exit_code"] == 1
    assert state_error_summary(slim) == "ValueError: bad lr"
    assert state_error_summary(state) == "ValueError: bad lr"
    assert "error" in state  # the caller's mapping is untouched


def test_the_slim_run_state_of_a_run_without_an_error_is_unchanged():
    state = {"exit_code": 0}
    assert slim_run_state(state) is state
    assert slim_run_state(None) is None
    assert state_error_summary(state) is None
    assert state_error_summary(None) is None
