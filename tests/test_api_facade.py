"""Tests for version_stamp.api — the stamping facade for experiment modules.

TDD: these tests fail before api.py exists (ImportError) and pass after.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Expected surface (written once; test_exact_surface verifies the live __all__
# matches this list so that accidental additions or removals are caught).
# ---------------------------------------------------------------------------

_EXPECTED_ALL = [
    "CommandSpec",
    "register_command",
    "find_command",
    "register_dev_version_loader",
    "VMN_ARGS",
    "vmn_run",
    "INIT_FILENAME",
    "VMN_BE_TYPE_GIT",
    "VMN_LOGGER",
    "VMN_USER_NAME",
    "VersionControlStamper",
    "_DEFAULT_MAX_FILE_MB",
    "_DEFAULT_MAX_TOTAL_MB",
    "_DIFF_HASH_LENGTHS",
    "_LOCAL_GIT_TIMEOUT_SEC",
    "_NETWORK_GIT_TIMEOUT_SEC",
    "_UNTRACKED_CACHE_FILE",
    "_apply_dep_patches",
    "_apply_patches_to_workdir",
    "_apply_snapshot_patches",
    "_clone_at",
    "_clone_local_at",
    "_collect_untracked_tarball",
    "_commit_exists",
    "_complete_apps",
    "_compute_diff_hash",
    "_compute_verstr",
    "_diff_real_tree",
    "_diff_with_external_tool",
    "_ensure_trailing_newline",
    "_extract_untracked_tarball",
    "_fmt_size",
    "_format_dev_verstr",
    "_generate_dep_patches",
    "_generate_patches",
    "_get_repo_status",
    "_git",
    "_git_ok",
    "_hash_untracked_content",
    "_init_app",
    "_list_tarball_members",
    "_load_untracked_cache",
    "_materialize_for_diff",
    "_materialize_workdir",
    "_mb_from_env",
    "_predates_untracked_capture",
    "_reset_worktree",
    "_resolve_remote",
    "_shallow_clone_at",
    "_store_untracked_cache",
    "_strip_git_dirs",
    "_unique_snapshot_verstr",
    "_untracked_candidates",
    "_untracked_caps",
    "_within_caps",
    "app_name_to_tag_name",
    "copy_untracked_files",
    "core_utils",
    "create_dep_worktree",
    "dep_base_commit",
    "deserialize_tag_name",
    "ensure_logger",
    "gather_create_data",
    "get_base_vmn_version",
    "get_client",
    "get_dirty_states",
    "get_git_difftool",
    "get_repo_lock",
    "group_commits",
    "handle_init",
    "init_needed",
    "auto_init_if_needed",
    "READ_ONLY_EXPECTED",
    "READ_ONLY_OPTIONAL",
    "island_layout",
    "measure_runtime_decorator",
    "now_iso",
    "parse_record_metadata",
    "payload_from_tarball",
    "remove_registered_worktree",
    "render_tree_diff",
    "resolve_root_path",
    "sha256_file",
    "tag_name_to_app_name",
    "untracked_payload",
    "valid_app_path",
    "valid_path_component",
    "version",
    "yaml_safe_load",
    # snapshot capture + store (version_stamp.snapshot)
    "SnapshotCapture",
    "capture_identity",
    "ensure_code",
    "build_record_metadata",
    "patch_summary",
    "open_snapshot_stores",
    "restore_record",
    "register_snapshot_store_opener",
    "LocalRecordStore",
    "relative_timestamp",
    "export_tree",
]

_REPO_ROOT = Path(__file__).parent.parent


def test_exact_surface():
    """api.__all__ sorted exactly matches the expected list in this file."""
    import version_stamp.api as api

    assert sorted(api.__all__) == sorted(_EXPECTED_ALL), (
        "api.__all__ surface has drifted; update _EXPECTED_ALL in this test "
        "and the _LAZY_REGISTRY in api.py together"
    )


def test_every_name_resolves():
    """Every name in api.__all__ can be resolved via getattr without error."""
    import version_stamp.api as api

    errors = []
    for name in api.__all__:
        try:
            getattr(api, name)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        pytest.fail("Names failed to resolve:\n" + "\n".join(errors))


def test_import_loads_no_experiment_modules():
    """Importing version_stamp.api must not load any experiment module or git."""
    code = (
        "import sys\n"
        "import version_stamp.api\n"
        "\n"
        "FORBIDDEN_PREFIXES = (\n"
        "    'vmn_exp.sdk',\n"
        "    'vmn_exp.ui',\n"
        "    'vmn_exp.snapshot',\n"
        "    'vmn_exp.cli.experiment',\n"
        ")\n"
        "FORBIDDEN_EXACT = {\n"
        "    'vmn_exp.core.jsonl_tail',\n"
        "    'vmn_exp.core.background',\n"
        "    'vmn_exp.core.best_effort',\n"
        "    'vmn_exp.core.record_files',\n"
        "}\n"
        "\n"
        "loaded = []\n"
        "for m in sys.modules:\n"
        "    if m.startswith('version_stamp.core.experiment_'):\n"
        "        loaded.append(m)\n"
        "    elif any(\n"
        "        m == p or m.startswith(p + '.') or m.startswith(p + '_')\n"
        "        for p in FORBIDDEN_PREFIXES\n"
        "    ):\n"
        "        loaded.append(m)\n"
        "    elif m in FORBIDDEN_EXACT:\n"
        "        loaded.append(m)\n"
        "    elif m == 'git' or m.startswith('git.'):\n"
        "        loaded.append(m)\n"
        "\n"
        "if loaded:\n"
        "    print('FORBIDDEN:' + ','.join(sorted(loaded)))\n"
        "    import sys as _sys; _sys.exit(1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(_REPO_ROOT),
    )
    if result.returncode != 0:
        pytest.fail(
            f"import version_stamp.api loaded forbidden modules:\n"
            f"{result.stdout.strip()}\n"
            f"stderr: {result.stderr[:400]}"
        )


def test_names_are_same_objects():
    """Each resolved name is the identical object as in the source module."""
    import version_stamp.api as api

    # (source_module, source_attr, api_name)
    checks = [
        # core.logging
        ("version_stamp.core.logging", "VMN_LOGGER", "VMN_LOGGER"),
        ("version_stamp.core.logging", "ensure_logger", "ensure_logger"),
        ("version_stamp.core.logging", "measure_runtime_decorator", "measure_runtime_decorator"),
        # core.utils
        ("version_stamp.core.utils", "now_iso", "now_iso"),
        ("version_stamp.core.utils", "parse_record_metadata", "parse_record_metadata"),
        ("version_stamp.core.utils", "resolve_root_path", "resolve_root_path"),
        ("version_stamp.core.utils", "sha256_file", "sha256_file"),
        ("version_stamp.core.utils", "valid_app_path", "valid_app_path"),
        ("version_stamp.core.utils", "valid_path_component", "valid_path_component"),
        ("version_stamp.core.utils", "yaml_safe_load", "yaml_safe_load"),
        # core.constants
        ("version_stamp.core.constants", "VMN_BE_TYPE_GIT", "VMN_BE_TYPE_GIT"),
        ("version_stamp.core.constants", "VMN_USER_NAME", "VMN_USER_NAME"),
        # cli.constants
        ("version_stamp.cli.constants", "INIT_FILENAME", "INIT_FILENAME"),
        # core.repo_lock
        ("version_stamp.core.repo_lock", "get_repo_lock", "get_repo_lock"),
        # core.version_math
        ("version_stamp.core.version_math", "app_name_to_tag_name", "app_name_to_tag_name"),
        ("version_stamp.core.version_math", "deserialize_tag_name", "deserialize_tag_name"),
        ("version_stamp.core.version_math", "get_base_vmn_version", "get_base_vmn_version"),
        ("version_stamp.core.version_math", "tag_name_to_app_name", "tag_name_to_app_name"),
        # core.changelog
        ("version_stamp.core.changelog", "group_commits", "group_commits"),
        # version (the version_stamp.version module)
        ("version_stamp", "version", "version"),
        # devversion.capture
        ("version_stamp.devversion.capture", "gather_create_data", "gather_create_data"),
        ("version_stamp.devversion.capture", "_compute_diff_hash", "_compute_diff_hash"),
        ("version_stamp.devversion.capture", "_DIFF_HASH_LENGTHS", "_DIFF_HASH_LENGTHS"),
        # devversion.apply
        ("version_stamp.devversion.apply", "_reset_worktree", "_reset_worktree"),
        ("version_stamp.devversion.apply", "_apply_dep_patches", "_apply_dep_patches"),
        # devversion.materialize
        ("version_stamp.devversion.materialize", "get_git_difftool", "get_git_difftool"),
        ("version_stamp.devversion.materialize", "_LOCAL_GIT_TIMEOUT_SEC", "_LOCAL_GIT_TIMEOUT_SEC"),
        # devversion.untracked
        ("version_stamp.devversion.untracked", "copy_untracked_files", "copy_untracked_files"),
        ("version_stamp.devversion.untracked", "_DEFAULT_MAX_FILE_MB", "_DEFAULT_MAX_FILE_MB"),
        ("version_stamp.devversion.untracked", "payload_from_tarball", "payload_from_tarball"),
    ]
    failures = []
    for mod_path, attr, api_name in checks:
        mod = importlib.import_module(mod_path)
        expected = getattr(mod, attr)
        actual = getattr(api, api_name)
        if actual is not expected:
            failures.append(
                f"api.{api_name} is not the same object as {mod_path}.{attr} "
                f"({type(actual)} vs {type(expected)})"
            )
    if failures:
        pytest.fail("\n".join(failures))
