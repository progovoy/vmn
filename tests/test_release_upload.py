"""`make upload` routes each built file to its PyPI project's .pypirc section."""
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [
    "vmn-0.10.3-py3-none-any.whl", "vmn-0.10.3.tar.gz",
    "vmn_exp-0.1.1-py3-none-any.whl", "vmn_exp-0.1.1.tar.gz",
    "vmn_exp_sdk-0.1.1-py3-none-any.whl", "vmn_exp_sdk-0.1.1.tar.gz",
]


def _upload(tmp_path, pypirc):
    dist = tmp_path / "dist"
    dist.mkdir()
    for name in FILES:
        (dist / name).write_text("")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".pypirc").write_text(pypirc)
    proc = subprocess.run(
        ["make", "-s", "-C", ROOT, "upload", f"DIST={dist}", "TWINE=echo twine"],
        capture_output=True, text=True, env={**os.environ, "HOME": str(home)},
    )
    assert proc.returncode == 0, proc.stderr
    return {
        os.path.basename(line.split()[-1]): line.split("-r ")[1].split()[0]
        for line in proc.stdout.splitlines() if line.startswith("twine upload")
    }


@pytest.mark.parametrize("sections, expected", [
    ("[pypi]\n[vmn-exp]\n[vmn-exp-sdk]\n",
     {"vmn": "pypi", "vmn_exp": "vmn-exp", "vmn_exp_sdk": "vmn-exp-sdk"}),
    # One account-wide token in [pypi] covers every project.
    ("[pypi]\n", {"vmn": "pypi", "vmn_exp": "pypi", "vmn_exp_sdk": "pypi"}),
])
def test_each_file_goes_to_its_projects_section(tmp_path, sections, expected):
    routed = _upload(tmp_path, sections)
    assert len(routed) == len(FILES)
    for name, section in routed.items():
        dist = name.split("-")[0]
        assert section == expected[dist], (name, section)
