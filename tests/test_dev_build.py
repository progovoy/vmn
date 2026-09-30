import os
import subprocess

from version_stamp import version as version_mod
from version_stamp.core import dev_build

from helpers import _PY, _SRC_PATH


def test_source_checkout_is_dev_build():
    assert dev_build.is_dev_build()


def test_installed_package_is_not_dev_build(tmp_path):
    package_dir = tmp_path / "site-packages" / "version_stamp"
    package_dir.mkdir(parents=True)

    assert not dev_build.is_dev_build(str(package_dir))


def test_display_version_marks_dev_build():
    assert dev_build.display_version() == f"{version_mod.version}+dev"


def test_display_version_of_installed_package_is_plain(monkeypatch):
    monkeypatch.setattr(dev_build, "is_dev_build", lambda: False)

    assert dev_build.display_version() == version_mod.version


def test_cli_version_marks_dev_build():
    env = dict(os.environ, PYTHONPATH=_SRC_PATH)
    out = subprocess.run(
        [_PY, "-m", "version_stamp.cli", "--version"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert out.strip() == f"{version_mod.version}+dev"

