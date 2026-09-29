"""version_stamp/api.py — The only stamping module that vmn_exp may import.

Every experiment-side import of a stamping function or constant routes through
this facade so the boundary enforced by tests/test_architecture_boundary.py has
a single audited surface to check.

Boundary rules (see PLAN.md §2.2):
  R1  vmn_exp.* → version_stamp.* only via this module.
  R3  ``import version_stamp.api`` loads no experiment module and no ``git``.

All 95 names are resolved lazily via PEP 562 ``__getattr__`` from the
``_LAZY_REGISTRY`` table below.  Each lookup caches the result in the module
namespace so repeated accesses pay only one ``importlib.import_module`` call.

Usage in experiment code:
    from version_stamp.api import VMN_LOGGER, resolve_root_path
    # mock.patch("version_stamp.core.logging.VMN_LOGGER", ...) still works
    # because __getattr__ returns the same object — identity is preserved.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# name → "dotted.module:attribute"  (all lookups are lazy)
# ---------------------------------------------------------------------------

_LAZY_REGISTRY: dict[str, str] = {
    # --- version_stamp.core.logging ----------------------------------------
    "VMN_LOGGER":                  "version_stamp.core.logging:VMN_LOGGER",
    "ensure_logger":               "version_stamp.core.logging:ensure_logger",
    "measure_runtime_decorator":   "version_stamp.core.logging:measure_runtime_decorator",
    # --- version_stamp.core.utils ------------------------------------------
    "now_iso":                     "version_stamp.core.utils:now_iso",
    "parse_record_metadata":       "version_stamp.core.utils:parse_record_metadata",
    "resolve_root_path":           "version_stamp.core.utils:resolve_root_path",
    "sha256_file":                 "version_stamp.core.utils:sha256_file",
    "valid_app_path":              "version_stamp.core.utils:valid_app_path",
    "valid_path_component":        "version_stamp.core.utils:valid_path_component",
    "yaml_safe_load":              "version_stamp.core.utils:yaml_safe_load",
    # --- version_stamp.core.constants --------------------------------------
    "VMN_BE_TYPE_GIT":             "version_stamp.core.constants:VMN_BE_TYPE_GIT",
    "VMN_USER_NAME":               "version_stamp.core.constants:VMN_USER_NAME",
    # --- version_stamp.cli.constants ---------------------------------------
    "INIT_FILENAME":               "version_stamp.cli.constants:INIT_FILENAME",
    # --- version_stamp.core.repo_lock --------------------------------------
    "get_repo_lock":               "version_stamp.core.repo_lock:get_repo_lock",
    # --- version_stamp.core.version_math -----------------------------------
    "app_name_to_tag_name":        "version_stamp.core.version_math:app_name_to_tag_name",
    "deserialize_tag_name":        "version_stamp.core.version_math:deserialize_tag_name",
    "get_base_vmn_version":        "version_stamp.core.version_math:get_base_vmn_version",
    "tag_name_to_app_name":        "version_stamp.core.version_math:tag_name_to_app_name",
    # --- version_stamp.core (module accessor for call-time patching) -------
    "core_utils":                  "version_stamp.core:utils",
    # --- version_stamp.core.changelog --------------------------------------
    "group_commits":               "version_stamp.core.changelog:group_commits",
    # --- version (version_stamp.version module re-exported as a module) ----
    # ui/server.py: from version_stamp import version as version_mod
    "version":                     "version_stamp:version",
    # --- heavy: loaded only when experiment code calls into stamping --------
    "VersionControlStamper":       "version_stamp.stamping.publisher:VersionControlStamper",
    "_get_repo_status":            "version_stamp.cli.commands:_get_repo_status",
    "_init_app":                   "version_stamp.cli.commands:_init_app",
    "handle_init":                 "version_stamp.cli.commands:handle_init",
    "get_dirty_states":            "version_stamp.cli.output:get_dirty_states",
    "get_client":                  "version_stamp.backends.factory:get_client",
    "_complete_apps":              "version_stamp.cli.completion:_complete_apps",
    # --- plugin hooks and the CLI runner, for vmn-exp's commands ------------
    "CommandSpec":                 "version_stamp.cli.plugin_api:CommandSpec",
    "register_command":            "version_stamp.cli.plugin_api:register",
    "find_command":                "version_stamp.cli.plugin_api:find",
    "register_dev_version_loader": "version_stamp.cli.plugin_api:register_dev_version_loader",
    "VMN_ARGS":                    "version_stamp.cli.constants:VMN_ARGS",
    "vmn_run":                     "version_stamp.cli.entry:vmn_run",
    # --- worktree helpers (layout + detached worktrees), for vmn-exp rerun --
    "island_layout":               "version_stamp.cli.worktree_create:_island_layout",
    "create_dep_worktree":         "version_stamp.cli.worktree_git:create_dep_worktree",
    "remove_registered_worktree":  "version_stamp.cli.worktree_git:remove_registered_worktree",
    # --- version_stamp.devversion.apply ------------------------------------
    "_apply_dep_patches":          "version_stamp.devversion.apply:_apply_dep_patches",
    "_apply_patches_to_workdir":   "version_stamp.devversion.apply:_apply_patches_to_workdir",
    "_apply_snapshot_patches":     "version_stamp.devversion.apply:_apply_snapshot_patches",
    "_reset_worktree":             "version_stamp.devversion.apply:_reset_worktree",
    # --- version_stamp.devversion.capture ----------------------------------
    "_compute_diff_hash":          "version_stamp.devversion.capture:_compute_diff_hash",
    "_compute_verstr":             "version_stamp.devversion.capture:_compute_verstr",
    "_DIFF_HASH_LENGTHS":          "version_stamp.devversion.capture:_DIFF_HASH_LENGTHS",
    "_format_dev_verstr":          "version_stamp.devversion.capture:_format_dev_verstr",
    "_generate_dep_patches":       "version_stamp.devversion.capture:_generate_dep_patches",
    "_generate_patches":           "version_stamp.devversion.capture:_generate_patches",
    "_stored_diff_hash":           "version_stamp.devversion.capture:_stored_diff_hash",
    "_unique_snapshot_verstr":     "version_stamp.devversion.capture:_unique_snapshot_verstr",
    "gather_create_data":          "version_stamp.devversion.capture:gather_create_data",
    # --- version_stamp.devversion.materialize ------------------------------
    "_clone_at":                   "version_stamp.devversion.materialize:_clone_at",
    "_clone_local_at":             "version_stamp.devversion.materialize:_clone_local_at",
    "_commit_exists":              "version_stamp.devversion.materialize:_commit_exists",
    "_diff_real_tree":             "version_stamp.devversion.materialize:_diff_real_tree",
    "_diff_with_external_tool":    "version_stamp.devversion.materialize:_diff_with_external_tool",
    "_git":                        "version_stamp.devversion.materialize:_git",
    "_git_ok":                     "version_stamp.devversion.materialize:_git_ok",
    "_LOCAL_GIT_TIMEOUT_SEC":      "version_stamp.devversion.materialize:_LOCAL_GIT_TIMEOUT_SEC",
    "_materialize_for_diff":       "version_stamp.devversion.materialize:_materialize_for_diff",
    "_materialize_workdir":        "version_stamp.devversion.materialize:_materialize_workdir",
    "_NETWORK_GIT_TIMEOUT_SEC":    "version_stamp.devversion.materialize:_NETWORK_GIT_TIMEOUT_SEC",
    "_predates_untracked_capture": "version_stamp.devversion.materialize:_predates_untracked_capture",
    "_resolve_remote":             "version_stamp.devversion.materialize:_resolve_remote",
    "_shallow_clone_at":           "version_stamp.devversion.materialize:_shallow_clone_at",
    "_strip_git_dirs":             "version_stamp.devversion.materialize:_strip_git_dirs",
    "_write_snapshot_to_dir":      "version_stamp.devversion.materialize:_write_snapshot_to_dir",
    "get_git_difftool":            "version_stamp.devversion.materialize:get_git_difftool",
    "render_tree_diff":            "version_stamp.devversion.materialize:render_tree_diff",
    # --- version_stamp.devversion.untracked --------------------------------
    "_collect_untracked_tarball":  "version_stamp.devversion.untracked:_collect_untracked_tarball",
    "_DEFAULT_MAX_FILE_MB":        "version_stamp.devversion.untracked:_DEFAULT_MAX_FILE_MB",
    "_DEFAULT_MAX_TOTAL_MB":       "version_stamp.devversion.untracked:_DEFAULT_MAX_TOTAL_MB",
    "_ensure_trailing_newline":    "version_stamp.devversion.untracked:_ensure_trailing_newline",
    "_extract_untracked_tarball":  "version_stamp.devversion.untracked:_extract_untracked_tarball",
    "_fmt_size":                   "version_stamp.devversion.untracked:_fmt_size",
    "_hash_untracked_content":     "version_stamp.devversion.untracked:_hash_untracked_content",
    "_list_tarball_members":       "version_stamp.devversion.untracked:_list_tarball_members",
    "_load_untracked_cache":       "version_stamp.devversion.untracked:_load_untracked_cache",
    "_mb_from_env":                "version_stamp.devversion.untracked:_mb_from_env",
    "_store_untracked_cache":      "version_stamp.devversion.untracked:_store_untracked_cache",
    "_UNTRACKED_CACHE_FILE":       "version_stamp.devversion.untracked:_UNTRACKED_CACHE_FILE",
    "_untracked_candidates":       "version_stamp.devversion.untracked:_untracked_candidates",
    "_untracked_caps":             "version_stamp.devversion.untracked:_untracked_caps",
    "_within_caps":                "version_stamp.devversion.untracked:_within_caps",
    "copy_untracked_files":        "version_stamp.devversion.untracked:copy_untracked_files",
    "payload_from_tarball":        "version_stamp.devversion.untracked:payload_from_tarball",
    "untracked_payload":           "version_stamp.devversion.untracked:untracked_payload",
    # --- version_stamp.snapshot (capture + record stores) ------------------
    "SnapshotCapture":             "version_stamp.snapshot.capture:SnapshotCapture",
    "capture_identity":            "version_stamp.snapshot.capture:capture_identity",
    "ensure_code":                 "version_stamp.snapshot.capture:ensure_code",
    "build_record_metadata":       "version_stamp.snapshot.record:build_record_metadata",
    "patch_summary":               "version_stamp.snapshot.record:patch_summary",
    "open_snapshot_stores":        "version_stamp.snapshot.stores:open_snapshot_stores",
    "register_snapshot_store_opener": "version_stamp.cli.plugin_api:register_snapshot_store_opener",
    "LocalRecordStore":            "version_stamp.snapshot.local_store:LocalRecordStore",
    "relative_timestamp":          "version_stamp.snapshot.listing:relative_timestamp",
}

# __all__ is the sorted key set of the registry — the single source of truth.
__all__: list[str] = sorted(_LAZY_REGISTRY)


def __getattr__(name: str) -> object:
    if name not in _LAZY_REGISTRY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod_path, attr = _LAZY_REGISTRY[name].split(":", 1)
    import importlib
    mod = importlib.import_module(mod_path)
    val = getattr(mod, attr)
    # Cache in module namespace: subsequent ``from version_stamp.api import X``
    # and ``version_stamp.api.X`` attribute lookups skip __getattr__ entirely.
    globals()[name] = val
    return val
