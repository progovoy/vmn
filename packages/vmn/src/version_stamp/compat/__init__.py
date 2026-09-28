"""Legacy format compatibility layer.

Each submodule handles forward-porting one legacy format or convention.
When a compat layer reaches end-of-life, delete its module, remove its
call site (a one-liner import), and delete the matching tests/compat/ file.

Modules:
    branch_conf        – flat/nested branch conf → canonical layout migration
    tag_format_039     – vmn 0.3.9 tag format (.0 suffix, "Automatic" messages)
    version_file_084   – vmn 0.8.4 version file (separate prerelease fields)
    template_format    – old default template → new default
    config_keys        – deprecated/renamed config keys
    release_mode       – "micro" → "hotfix" alias
    completion         – legacy shell completion script stripping
    local_file_paths   – verinfo/ → snapshots/ directory fallback
    worktree_manifest  – island manifest without source_path
    goto_changesets    – tags lacking changesets data
"""
