"""Plan 22 §6 over HTTP: the page names the aggregate ``agg=`` resolved to
(the app's conf default, the checkout branch's conf respected, F3), counts
the running rows (F4), and clamps its size (F5)."""
import os

import pytest
import yaml
from test_ui_leaderboard_groups_route import (  # noqa: F401
    APP,
    BASE,
    _client,
    _conf,
    _record,
    repo,
)

pytest.importorskip("fastapi")


def _head(root, text):
    with open(os.path.join(root, ".git", "HEAD"), "w") as f:
        f.write(text)


def _branch_conf(root, branch, experiment):
    folder = os.path.join(root, ".vmn", APP, "branch_conf", *branch.split("/"))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "conf.yml"), "w") as f:
        yaml.dump({"conf": {"experiment": experiment}}, f)


def _aggregate(tmp_path, root, **params):
    body = _client(tmp_path, root).get(BASE, params={"group": "parent", **params}).json()
    return body["aggregate"]


def test_the_page_names_the_mean_by_default(tmp_path, repo):  # noqa: F811
    assert _aggregate(tmp_path, repo[0]) == "mean"


def test_the_page_names_the_apps_conf_default(tmp_path, repo):  # noqa: F811
    root, _ = repo
    _conf(root, {"ui": {"group_aggregate": "median"}})
    client = _client(tmp_path, root)
    assert client.get(BASE, params={"group": "parent"}).json()["aggregate"] == "median"
    explicit = client.get(BASE, params={"group": "parent", "agg": "best"}).json()
    assert explicit["aggregate"] == "best"


def test_an_invalid_conf_default_is_named_the_mean(tmp_path, repo):  # noqa: F811
    root, _ = repo
    _conf(root, {"ui": {"group_aggregate": "sum"}})
    assert _aggregate(tmp_path, root) == "mean"


def test_the_checkout_branchs_conf_wins_over_the_apps(tmp_path, repo):  # noqa: F811
    root, runs = repo
    _conf(root, {"metrics": {"loss": {"goal": "min"}}, "ui": {"group_aggregate": "median"}})
    _branch_conf(root, "feat/x", {"metrics": {"loss": {"goal": "min"}},
                                  "ui": {"group_aggregate": "min"}})
    _head(root, "ref: refs/heads/feat/x\n")
    body = _client(tmp_path, root).get(BASE, params={"group": "parent", "sort": "loss"}).json()
    assert body["aggregate"] == "min"
    assert [g["key"] for g in body["groups"]][:2] == [runs[1], runs[4]]


@pytest.mark.parametrize("head", [
    "ref: refs/heads/main\n", "0123456789abcdef0123456789abcdef01234567\n",
])
def test_another_branch_or_a_detached_head_reads_the_apps_conf(tmp_path, repo, head):  # noqa: F811
    root, _ = repo
    _conf(root, {"ui": {"group_aggregate": "median"}})
    _branch_conf(root, "feat/x", {"ui": {"group_aggregate": "min"}})
    _head(root, head)
    assert _aggregate(tmp_path, root) == "median"


def test_a_worktree_checkout_follows_its_gitdir(tmp_path, repo):  # noqa: F811
    root, _ = repo
    gitdir = tmp_path / "main-repo" / ".git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/feat/x\n")
    os.rmdir(os.path.join(root, ".git"))
    with open(os.path.join(root, ".git"), "w") as f:
        f.write(f"gitdir: {gitdir}\n")
    _conf(root, {"ui": {"group_aggregate": "median"}})
    _branch_conf(root, "feat/x", {"ui": {"group_aggregate": "max"}})
    assert _aggregate(tmp_path, root) == "max"


def test_the_page_counts_running_rows(tmp_path, repo):  # noqa: F811
    body = _client(tmp_path, repo[0]).get(BASE, params={"group": "parent"}).json()
    assert body["running"] == 0


def _on_branch(verstr_path, branch):
    path = os.path.join(verstr_path, "metadata.yml")
    with open(path) as f:
        meta = yaml.safe_load(f)
    with open(path, "w") as f:
        yaml.dump(dict(meta, branch=branch), f)


@pytest.fixture
def wide(tmp_path):
    """56 runs on 56 branches; 55 of them inner runs of run 100."""
    root = tmp_path / "wide"
    (root / ".git").mkdir(parents=True)
    root = str(root)
    runs = os.path.join(root, ".vmn", "store", "runs", APP)
    _on_branch(os.path.join(runs, _record(root, 100, 1.0)), "b100")
    for n in range(1, 56):
        _on_branch(os.path.join(runs, _record(root, n, float(n), parent=100)), f"b{n}")
    return root


@pytest.mark.parametrize("limit, served", [(500, 50), (51, 50), (50, 50), (0, 1), (-1, 1)])
def test_a_page_of_groups_is_clamped_to_fifty(tmp_path, wide, limit, served):
    response = _client(tmp_path, wide).get(BASE, params={"group": "branch", "limit": limit})
    assert response.status_code == 200
    body = response.json()
    assert len(body["groups"]) == served
    assert body["total_groups"] == 56


def test_the_page_size_cap_is_fifty_groups_and_five_thousand_rows():
    from vmn_exp.ui.routes_leaderboard import grouped_page

    assert grouped_page(500, 100) == (50, 100)
    assert grouped_page(None, 10) == (50, 10)
    assert grouped_page(0, 0) == (1, 1)
    assert grouped_page(50, 1000) == (50, 100)
    for limit in range(-1, 60):
        for per_group in (-5, 1, 99, 100, 101, 5000):
            groups, rows = grouped_page(limit, per_group)
            assert 1 <= groups <= 50 and 1 <= rows <= 100 and groups * rows <= 5000


def test_one_groups_rows_page_is_not_cut_to_fifty(tmp_path, wide):
    key = "0.0.1-dev.abc1234.def5678.r100"
    page = _client(tmp_path, wide).get(
        BASE, params={"group": "parent", "group_key": key, "limit": 500}).json()
    assert len(page["rows"]) == 55
