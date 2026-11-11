"""The shell's git context and the stamp-tree fingerprint on scripted git
output (plan 44 G5): no real git process."""
import subprocess

from fakes.processes import HANG, FakeProcesses
from vmn_exp.ui.git_context import GIT_STATUS, git_context
from vmn_exp.ui.tree_cache import UNKNOWN, TreeCache, versions_fingerprint

HEAD = "a" * 40
TAGS = ["git", "tag", "--list", "app_*"]


def _done(argv, code=0, out="", err=""):
    return subprocess.CompletedProcess(argv, code, stdout=out, stderr=err)


def test_git_timeout_is_reported_not_raised():
    assert git_context("/repo", FakeProcesses({tuple(GIT_STATUS): HANG}))["error"] == "timeout"


def test_missing_git_is_reported_not_raised():
    assert git_context("/repo", FakeProcesses())["error"]


def test_status_text_is_parsed():
    out = f"# branch.oid {HEAD}\n# branch.head main\n1 .M N... 100644 100644 100644 x y a.txt\n"
    processes = FakeProcesses({tuple(GIT_STATUS): _done(GIT_STATUS, out=out)})
    context = git_context("/repo", processes)
    assert (context["branch"], context["head_short"], context["dirty"]) == ("main", "aaaaaaa", True)
    assert processes.calls[0][1]["cwd"] == "/repo" and processes.calls[0][1]["timeout"] == 2


def test_failed_git_reports_its_first_stderr_line():
    processes = FakeProcesses({tuple(GIT_STATUS): _done(GIT_STATUS, 128, err="fatal: not a repo\nmore")})
    assert git_context("/repo", processes)["error"] == "fatal: not a repo"


def test_fingerprint_follows_the_tag_list():
    one = versions_fingerprint("/repo", "app", FakeProcesses({tuple(TAGS): _done(TAGS, out="app_0.0.1\n")}))
    two = versions_fingerprint("/repo", "app", FakeProcesses({tuple(TAGS): _done(TAGS, out="app_0.0.2\n")}))
    assert UNKNOWN not in (one, two) and one != two


def test_fingerprint_is_unknown_when_tags_cannot_be_listed():
    failed = FakeProcesses({tuple(TAGS): _done(TAGS, 128)})
    assert versions_fingerprint("/repo", "app", failed) == UNKNOWN
    assert versions_fingerprint("/repo", "app", FakeProcesses()) == UNKNOWN


def test_tree_cache_reuses_a_value_while_the_fingerprint_holds():
    cache, computed = TreeCache(), []

    def compute():
        computed.append(1)
        return len(computed)

    assert cache.get("fp1", "/repo", "app", "dag", compute) == 1
    assert cache.get("fp1", "/repo", "app", "dag", compute) == 1
    assert cache.get("fp2", "/repo", "app", "dag", compute) == 2
    assert cache.get(UNKNOWN, "/repo", "app", "dag", compute) == 3
