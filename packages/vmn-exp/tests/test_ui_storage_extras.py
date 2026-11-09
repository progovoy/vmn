"""``vmn-exp ui`` on a Google Cloud Storage or Azure store without its storage
package refuses to start with the extra to install, as an S3 store without
boto3 does (plan 31 §4.4)."""
import importlib.util

import pytest

pytest.importorskip("fastapi")

from test_ui_cli import _run_handle_ui  # noqa: E402
from test_ui_s3_extra import _server_yml  # noqa: E402

CASES = [
    ("gs://bkt/team", "google", 'pip install "vmn-exp[ui,gcs]"'),
    ("az://container/team", "azure", 'pip install "vmn-exp[ui,azure]"'),
]


def _hide(monkeypatch, top_level):
    """Act as if *top_level* is not installed: ``find_spec`` of a dotted name
    under it raises, as the real one does when the parent is missing."""
    real = importlib.util.find_spec

    def find_spec(name, *args, **kwargs):
        if name == top_level:
            return None
        if name.startswith(top_level + "."):
            raise ModuleNotFoundError(f"No module named '{top_level}'", name=top_level)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)


ARGV = {
    "--store": lambda tmp_path, store: ["--store", store],
    "server.yml": lambda tmp_path, store: ["--config", _server_yml(tmp_path, store)],
}


@pytest.mark.parametrize("argv", ARGV.values(), ids=ARGV.keys())
@pytest.mark.parametrize("store,top_level,hint", CASES)
def test_a_store_without_its_package_refuses_to_start(
        tmp_path, monkeypatch, capfd, store, top_level, hint, argv):
    _hide(monkeypatch, top_level)

    rc, calls = _run_handle_ui(tmp_path, monkeypatch, argv(tmp_path, store))

    assert rc != 0
    assert calls == []
    assert hint in capfd.readouterr().err
