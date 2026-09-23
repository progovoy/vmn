"""list_versions: one git call, linear in the number of tags."""
import subprocess
import time

import git
import yaml

from version_stamp.ui.readers import versions as ver_reader
from helpers import _init_app, _run_vmn_init, _stamp_app


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo_with_tags(tmp_path, count):
    repo = str(tmp_path)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    for i in range(count):
        msg = yaml.dump(
            {
                "stamping": {
                    "app": {
                        "release_mode": "patch",
                        "previous_version": f"0.0.{i - 1}" if i else None,
                        "stamped_on_branch": "main",
                        "changesets": {".": {"hash": head}},
                    }
                }
            }
        )
        _git(repo, "tag", "-a", f"app_0.0.{i}", "-m", f"app: 0.0.{i}\n\n{msg}")
    _git(repo, "pack-refs", "--all")
    return repo, head


def test_list_versions_is_linear_in_tag_count(tmp_path):
    repo, _ = _repo_with_tags(tmp_path, 1000)

    start = time.monotonic()
    rows = ver_reader.list_versions(repo, "app")
    elapsed = time.monotonic() - start

    assert len(rows) == 1000
    assert elapsed < 1.5, f"list_versions took {elapsed:.2f}s for 1000 tags"


def test_list_versions_rows_carry_tag_metadata(tmp_path):
    repo, head = _repo_with_tags(tmp_path, 3)

    rows = ver_reader.list_versions(repo, "app")

    assert [r["verstr"] for r in rows] == ["0.0.0", "0.0.1", "0.0.2"]
    last = rows[-1]
    assert last["tag"] == "app_0.0.2"
    assert last["kind"] == "version"
    assert last["release_mode"] == "patch"
    assert last["previous_version"] == "0.0.1"
    assert last["branch"] == "main"
    assert last["commit"] == head
    tagged = git.Repo(repo).tags["app_0.0.2"].tag.tagged_date
    assert last["timestamp"] == tagged


def test_list_versions_tolerates_lightweight_and_foreign_tags(tmp_path):
    repo, _ = _repo_with_tags(tmp_path, 1)
    _git(repo, "tag", "app_0.0.9")  # lightweight: no YAML, no tagger date
    _git(repo, "tag", "-a", "app_0.0.8", "-m", "not: [valid yaml")
    _git(repo, "tag", "-a", "other_1.0.0", "-m", "x")

    rows = {r["verstr"]: r for r in ver_reader.list_versions(repo, "app")}

    assert set(rows) == {"0.0.0", "0.0.8", "0.0.9"}
    assert rows["0.0.9"]["timestamp"] is None
    assert rows["0.0.9"]["release_mode"] is None
    assert rows["0.0.8"]["release_mode"] is None


def test_list_versions_matches_stamped_history(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    for i, mode in enumerate(("patch", "minor")):
        app_layout.write_file_commit_and_push("test_repo_0", "f.txt", str(i))
        err, _, _ = _stamp_app(app_layout.app_name, mode)
        assert err == 0

    rows = ver_reader.list_versions(app_layout.repo_path, app_layout.app_name)

    assert [r["verstr"] for r in rows] == ["0.0.0", "0.0.1", "0.1.0"]
    assert rows[-1]["previous_version"] == "0.0.1"
    assert rows[-1]["release_mode"] == "minor"
    assert all(isinstance(r["timestamp"], int) for r in rows)
