"""First-time vmn stamp should auto-init without producing ERROR messages."""
from helpers import _stamp_app
from version_stamp.core.logging import reset_logger


def test_first_stamp_auto_inits_without_errors(app_layout, capfd):
    """A fresh repo with no vmn init should stamp cleanly on first call."""
    reset_logger()
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")

    assert err == 0
    assert ver_info is not None
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    captured = capfd.readouterr()
    assert "[ERROR]" not in captured.err, (
        f"First stamp should not produce ERROR output, got:\n{captured.err}"
    )


def test_first_stamp_logs_init_progress(app_layout, capfd):
    """Auto-init should emit INFO messages about what it's doing."""
    reset_logger()
    _stamp_app(app_layout.app_name, "patch")

    captured = capfd.readouterr()
    assert "initializ" in captured.out.lower(), (
        f"Expected initialization progress in output, got:\n{captured.out}"
    )
