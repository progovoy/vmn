"""vmn-exp rerun places each dep at its recorded base (``dep_base_commits``),
not its stamp changeset, and a rerun's record keeps those bases."""
from test_exp_rerun_workdir import _commit, _git, _metadata, _prepare, ws  # noqa: F401

from version_stamp import api
from version_stamp.devversion.apply import dep_base_commit
from vmn_exp.core import rerun


def test_api_exposes_dep_base_commit():
    assert "dep_base_commit" in api.__all__
    assert api.dep_base_commit is dep_base_commit


def test_prepare_puts_a_dep_at_its_recorded_base(ws):  # noqa: F811
    metadata = _metadata(ws)
    moved = _commit(ws.dep, "moved.txt", "moved after the stamp\n")
    metadata["dep_base_commits"] = {"../repo1": moved}

    workdir = _prepare(ws, metadata, {})

    assert _git(f"{workdir.root}/repo1", "rev-parse", "HEAD") == moved


def test_rerun_template_copies_dep_base_commits():
    meta = {"verstr": "v", "base_commit": "c", "dep_base_commits": {"../d": "abc"}}

    template = rerun.rerun_template(meta, "v", None, "t")

    assert template["dep_base_commits"] == {"../d": "abc"}
