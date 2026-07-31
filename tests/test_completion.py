import argparse
import json
import os
import runpy
from types import SimpleNamespace

import pytest

from version_stamp.cli import completion


def _safe_legacy_rc_files(monkeypatch, tmp_path):
    paths = {
        "bash": tmp_path / "legacy-bashrc",
        "zsh": tmp_path / "legacy-zshrc",
        "fish": tmp_path / "legacy-fish-config",
        "tcsh": tmp_path / "legacy-tcshrc",
    }
    monkeypatch.setattr(
        completion,
        "RC_FILES",
        {shell: str(path) for shell, path in paths.items()},
        raising=False,
    )
    return paths


def test_print_completion_setup_generates_static_shellcode(capsys):
    assert completion.print_completion_setup("bash") == 0

    output = capsys.readouterr().out
    assert "_ARGCOMPLETE" in output
    assert "register-python-argcomplete" not in output


def test_tcsh_shellcode_uses_vmn_owned_helper(capsys):
    assert completion.print_completion_setup("tcsh") == 0

    output = capsys.readouterr().out
    assert "vmn-argcomplete-tcsh" in output
    assert "python-argcomplete-tcsh" not in output


def test_tcsh_helper_executes_vmn_with_argcomplete_environment(monkeypatch):
    calls = {"dup2": []}
    monkeypatch.setenv("COMMAND_LINE", "vmn show ser")
    monkeypatch.setattr(
        completion.sys, "stdout", SimpleNamespace(fileno=lambda: 17)
    )
    monkeypatch.setattr(os, "open", lambda *args: 23)
    monkeypatch.setattr(
        os, "dup2", lambda source, dest: calls["dup2"].append((source, dest))
    )
    monkeypatch.setattr(os, "close", lambda fd: calls.setdefault("closed", fd))

    def record_exec(file, args, env):
        calls["exec"] = (file, args, env)

    monkeypatch.setattr(os, "execvpe", record_exec)

    completion.tcsh_completion_main()

    executable, args, env = calls["exec"]
    assert executable == "vmn"
    assert args == ["vmn"]
    assert env["COMP_LINE"] == "vmn show ser"
    assert env["COMP_POINT"] == str(len("vmn show ser"))
    assert env["_ARGCOMPLETE"] == "1"
    assert env["_ARGCOMPLETE_SHELL"] == "tcsh"
    assert env["IFS"] == ""
    assert calls["dup2"] == [(17, 8), (23, 1), (23, 2)]


def test_setup_exposes_tcsh_helper_entry_point(monkeypatch):
    import setuptools

    captured = {}
    monkeypatch.setattr(setuptools, "setup", lambda **kwargs: captured.update(kwargs))

    runpy.run_path("setup.py")

    assert (
        "vmn-argcomplete-tcsh = "
        "version_stamp.cli.completion:tcsh_completion_main"
    ) in captured["entry_points"]["console_scripts"]


@pytest.mark.parametrize("shell", ["fish", "tcsh"])
def test_install_completion_is_idempotent_for_all_shells(
    shell, tmp_path, monkeypatch
):
    paths = _safe_legacy_rc_files(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert completion.install_completion(shell) == 0
    assert completion.install_completion(shell) == 0

    content = paths[shell].read_text()
    assert content.count("# vmn shell completion") == 1


def test_install_completion_embeds_shellcode_without_path_dependency(
    tmp_path, monkeypatch
):
    paths = _safe_legacy_rc_files(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert completion.install_completion("bash") == 0

    content = paths["bash"].read_text()
    assert "_ARGCOMPLETE" in content
    assert "register-python-argcomplete" not in content


def test_tcsh_install_reuses_existing_cshrc(tmp_path, monkeypatch):
    _safe_legacy_rc_files(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    cshrc = tmp_path / ".cshrc"
    cshrc.write_text("set prompt='safe'\n")

    assert completion.install_completion("tcsh") == 0

    assert "# vmn shell completion" in cshrc.read_text()
    assert not (tmp_path / ".tcshrc").exists()


def test_zsh_install_honors_zdotdir(tmp_path, monkeypatch):
    _safe_legacy_rc_files(monkeypatch, tmp_path)
    zdotdir = tmp_path / "zsh"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ZDOTDIR", str(zdotdir))

    assert completion.install_completion("zsh") == 0

    assert (zdotdir / ".zshrc").is_file()


def test_fish_install_honors_xdg_config_home(tmp_path, monkeypatch):
    _safe_legacy_rc_files(monkeypatch, tmp_path)
    config_home = tmp_path / "xdg"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    assert completion.install_completion("fish") == 0

    assert (config_home / "fish" / "config.fish").is_file()


def test_bash_install_uses_existing_bash_profile(tmp_path, monkeypatch):
    _safe_legacy_rc_files(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    bash_profile = tmp_path / ".bash_profile"
    bash_profile.write_text("export PROJECT=value\n")

    assert completion.install_completion("bash") == 0

    assert "# vmn shell completion" in bash_profile.read_text()
    assert not (tmp_path / ".bashrc").exists()


def test_install_completion_reports_filesystem_errors(
    tmp_path, monkeypatch, capsys
):
    _safe_legacy_rc_files(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    def fail_open(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr("builtins.open", fail_open)

    assert completion.install_completion("bash") == 1
    assert "read-only filesystem" in capsys.readouterr().err


def test_install_completion_preserves_rc_when_atomic_replace_fails(
    tmp_path, monkeypatch, capsys
):
    paths = _safe_legacy_rc_files(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    paths["bash"].write_text("export KEEP_ME=true\n")

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    assert completion.install_completion("bash") == 1
    assert paths["bash"].read_text() == "export KEEP_ME=true\n"
    assert "replace failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    "content",
    [
        f"rules\n{completion.COMPLETION_MARKER}\nbroken\n",
        f"rules\n{completion.COMPLETION_END_MARKER}\n",
        (
            f"{completion.COMPLETION_MARKER}\none\n"
            f"{completion.COMPLETION_MARKER}\ntwo\n"
            f"{completion.COMPLETION_END_MARKER}\n"
        ),
    ],
)
def test_install_completion_rejects_malformed_managed_blocks(
    content, tmp_path, monkeypatch, capsys
):
    paths = _safe_legacy_rc_files(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    paths["bash"].write_text(content)

    assert completion.install_completion("bash") == 1
    assert paths["bash"].read_text() == content
    assert "malformed" in capsys.readouterr().err.lower()


def test_app_completion_resolves_tilde_and_real_path(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    repo = home / "repo"
    app_dir = repo / ".vmn" / "service"
    nested = repo / "src" / "nested"
    app_dir.mkdir(parents=True)
    nested.mkdir(parents=True)
    (app_dir / "last_known_app_version.yml").write_text("version: 1.0.0\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VMN_WORKING_DIR", "~/repo/src/nested")

    assert completion.app_name_completer("ser", argparse.Namespace()) == [
        "service"
    ]


@pytest.mark.parametrize("reserved_segment", ["snapshots", "experiments"])
def test_app_completion_keeps_valid_reserved_path_segments(
    reserved_segment, tmp_path, monkeypatch
):
    app_dir = tmp_path / ".vmn" / "root" / reserved_segment / "service"
    app_dir.mkdir(parents=True)
    (app_dir / "last_known_app_version.yml").write_text("version: 1.0.0\n")
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))

    assert completion.app_name_completer("root/", argparse.Namespace()) == [
        f"root/{reserved_segment}/service"
    ]


def test_worktrees_remove_completes_island_names(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    island_root = tmp_path / "islands"
    (root / ".vmn").mkdir(parents=True)
    for name in ("feature-one", "feature-two", "other"):
        island_dir = island_root / name
        island_dir.mkdir(parents=True)
        (island_dir / "island.json").write_text(json.dumps({"name": name}))
    monkeypatch.setenv("VMN_WORKING_DIR", str(root))
    parsed_args = argparse.Namespace(
        command="worktrees",
        action="remove",
        base_path=str(island_root),
    )

    assert completion.app_name_completer("feature", parsed_args) == [
        "feature-one",
        "feature-two",
    ]


def test_setup_completion_uses_supported_default_completer_api(monkeypatch):
    import argcomplete

    calls = []
    monkeypatch.setattr(
        argcomplete,
        "autocomplete",
        lambda parser, **kwargs: calls.append((parser, kwargs)),
    )
    parser = argparse.ArgumentParser()

    completion.setup_completion(parser)

    assert calls[0][0] is parser
    default_completer = calls[0][1]["default_completer"]
    assert callable(default_completer)
    assert default_completer(
        "r",
        argparse.Namespace(command="worktrees"),
        action=SimpleNamespace(dest="action"),
    ) == ["remove"]
