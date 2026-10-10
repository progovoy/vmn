"""features_from_patches over what git itself prints: `git format-patch --stdout`
for local commits and `git diff --binary HEAD` for the dirty working tree."""
import os
import subprocess

import pytest
from vmn_exp.core.features import author_from_commits, features_from_patches

LONG_SUBJECT = ("try focal loss with gamma two on the long tail split and keep "
                "the old loss as a fallback")
ACCENT_SUBJECT = ("Café: essayer la perte focale avec gamma deux pour corriger le "
                  "rappel des classes minoritaires")
ATTRIBUTES = "*.py diff=python\n*.go diff=golang\n*.rs diff=rust\n*.c diff=cpp\n"
TAB = "\t"


def _body(indent, n=12):
    return "".join(f"{indent}v{i} = {i}\n" for i in range(n))


def _sources():
    return {
        ".gitattributes": ATTRIBUTES,
        "model.py": (f"import os\n\n\ndef train(x):\n{_body('    ')}    return x\n\n\n"
                     f"class Net:\n    def forward(self, x):\n{_body('        ')}"
                     "        return x\n"),
        "app.js": f"const a = 1;\n\nfunction loadData(path) {{\n{_body('  ')}}}\n",
        "server.go": ("package main\n\nfunc (s *Server) Start(ctx context.Context) error {\n"
                      f"{_body(TAB)}\treturn nil\n}}\n"),
        "lib.rs": f"pub fn parse(input: &str) -> usize {{\n{_body('    let ')}    0\n}}\n",
        "util.c": f"static int count_lines(const char *path)\n{{\n{_body('    int ')}}}\n",
        "old name.txt": "a\nb\nc\nd\n",
        "gone.txt": "bye\n",
    }


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               HOME=str(tmp_path), GIT_COMMITTER_NAME="C", GIT_COMMITTER_EMAIL="c@x.io")

    def git(*args, author=("Base", "base@x.io")):
        run_env = dict(env, GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1])
        return subprocess.run(["git", *args], cwd=path, env=run_env, check=True,
                              capture_output=True, text=True).stdout

    git("init", "-q", "-b", "main")
    _write(path, _sources())
    git("add", "-A")
    git("commit", "-qm", "base")
    git("tag", "base")
    return path, git


def _write(path, files):
    for name, text in files.items():
        mode = "wb" if isinstance(text, bytes) else "w"
        with open(path / name, mode) as f:
            f.write(text)


def _edit(path, name, old, new):
    text = (path / name).read_text()
    assert old in text
    (path / name).write_text(text.replace(old, new, 1))


@pytest.fixture
def worked(repo):
    """Three local commits on top of `base`, then a dirty working tree."""
    path, git = repo
    _edit(path, "model.py", "    v6 = 6", "    v6 = 66")
    _edit(path, "model.py", "        v6 = 6", "        v6 = 66")
    _write(path, {"img.bin": bytes(range(256))})
    git("mv", "old name.txt", "new name.txt")
    git("rm", "-q", "gone.txt")
    git("add", "-A")
    git("commit", "-qm", LONG_SUBJECT, author=("Jörg Müller", "j@x.io"))
    _edit(path, "server.go", "\tv6 = 6", "\tv6 = 66")
    _edit(path, "lib.rs", "let v6 = 6", "let v6 = 66")
    _write(path, {"fresh.py": "z = 1\n"})
    git("add", "-A")
    git("commit", "-qm", "wire the loss into go and rust", author=("Doe, John", "jd@x.io"))
    _edit(path, "app.js", "  v6 = 6", "  v6 = 66")
    git("commit", "-qam", ACCENT_SUBJECT, author=("Zoë", "z@x.io"))
    _edit(path, "util.c", "int v6 = 6", "int v6 = 66")
    _edit(path, "app.js", "  v9 = 9", "  v9 = 99")
    _write(path, {"untracked.txt": "not in any diff\n"})
    return path, git


def _features(git, *config):
    commits = git("format-patch", "--stdout", "base..HEAD")
    dirty = git(*config, "diff", "--binary", "HEAD")
    return features_from_patches([dirty, commits])


def test_real_git_output_yields_files_symbols_commits_and_authors(worked):
    _, git = worked
    result = _features(git)
    assert sorted(result["changed"]["files"]) == sorted([
        "app.js", "util.c", "gone.txt", "img.bin", "model.py", "new name.txt",
        "old name.txt", "fresh.py", "lib.rs", "server.go"])
    assert set(result["changed"]["symbols"]) == {
        "app.js::loadData", "util.c::count_lines", "model.py::train",
        "model.py::forward", "server.go::Start", "lib.rs::parse"}
    assert result["commits"] == [LONG_SUBJECT, "wire the loss into go and rust", ACCENT_SUBJECT]
    assert result["commit_authors"] == [
        {"name": "Jörg Müller", "email": "j@x.io"},
        {"name": "Doe, John", "email": "jd@x.io"},
        {"name": "Zoë", "email": "z@x.io"},
    ]
    assert author_from_commits(result["commit_authors"]) == {
        "git_user_email": "j@x.io", "source": "commit"}
    assert "truncated" not in result


def test_git_folds_and_encodes_the_headers_this_parser_undoes(worked):
    _, git = worked
    mbox = git("format-patch", "--stdout", "base..HEAD")
    assert mbox.startswith("From ") and f"Subject: [PATCH 1/3] {LONG_SUBJECT}" not in mbox
    assert "\nFrom: =?UTF-8?q?J=C3=B6rg" in mbox and '\nFrom: "Doe, John" <jd@x.io>' in mbox
    assert any(line.startswith(" =?UTF-8?q?") for line in mbox.splitlines())


def test_one_hunk_context_per_hunk_even_with_several_hunks_in_a_file(worked):
    _, git = worked
    hunks = [line for line in git("diff", "HEAD~3", "HEAD", "--", "model.py").splitlines()
             if line.startswith("@@")]
    assert len(hunks) == 2
    symbols = features_from_patches([git("diff", "HEAD~3", "HEAD")])["changed"]["symbols"]
    assert [s for s in symbols if s.startswith("model.py")] == ["model.py::train",
                                                                "model.py::forward"]


@pytest.mark.parametrize("config", [("-c", "diff.mnemonicPrefix=true"),
                                    ("-c", "diff.noprefix=true")])
def test_diff_prefix_configuration_does_not_change_the_features(worked, config):
    _, git = worked
    assert _features(git, *config) == _features(git)
