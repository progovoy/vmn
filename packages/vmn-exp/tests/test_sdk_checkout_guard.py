"""require_checkout: a run outside a git checkout fails with one clear error
that names the directory and the ways out (plan 38 A3)."""
import pytest

from vmn_exp.sdk.checkout_guard import require_checkout


def test_require_checkout_returns_the_root():
    assert require_checkout("/repo", "/repo/sub") == "/repo"


def test_require_checkout_raises_runtime_error_naming_the_directory_and_the_ways_out():
    with pytest.raises(RuntimeError) as exc:
        require_checkout(None, "/data/plain")
    message = str(exc.value)
    assert "/data/plain" in message
    assert "not inside a git checkout" in message
    assert "git init && git commit --allow-empty -m init" in message
    assert "VMN_SNAPSHOT_METADATA" in message


def test_the_message_never_mentions_vmn_logger():
    with pytest.raises(RuntimeError) as exc:
        require_checkout(None, "/data/plain")
    assert "VMN_LOGGER" not in str(exc.value)
    assert "logger" not in str(exc.value).lower()
