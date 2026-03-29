#!/usr/bin/env python3
from dataclasses import asdict, dataclass, field, fields
from typing import Optional, Set

from version_stamp.core.constants import VMN_OLD_TEMPLATE


# ── Version data classes ─────────────────────────────────────────────

@dataclass
class VersionProps:
    types: Set[str] = field(default_factory=lambda: {"version"})
    root_version: Optional[int] = None
    major: Optional[int] = None
    minor: Optional[int] = None
    patch: Optional[int] = None
    hotfix: Optional[int] = None
    prerelease: str = "release"
    rcn: Optional[int] = None
    buildmetadata: Optional[str] = None
    old_ver_format: bool = False


@dataclass
class TagProps(VersionProps):
    app_name: Optional[str] = None
    old_tag_format: bool = False
    verstr: Optional[str] = None


# ── Default template ─────────────────────────────────────────────────

_DEFAULT_TEMPLATE = (
    "[{major}][.{minor}][.{patch}][.{hotfix}]"
    "[-{prerelease}][.{rcn}][+{buildmetadata}]"
)


# ── Application configuration ────────────────────────────────────────

@dataclass
class AppConf:
    """Single source of truth for all per-app configuration flags.

    Field metadata keys:
        attr        – attribute name on IVersionsStamper (default: field name)
        ui_desc     – description shown in the interactive config TUI
        ui_type     – editor type: bool, string, choice, bool_or_dict, nested_dict
        ui_example  – example value shown for string fields
        ui_choices  – valid values for choice fields
        ui_editor   – custom editor name for nested_dict fields
                      (version_backends, deps, policies, external_services)
                      Omit for the generic YAML editor fallback.
    """

    template: str = field(
        default="",
        metadata={
            "ui_desc": (
                "Version display format. Use placeholders: {major}, {minor}, "
                "{patch}, {hotfix}, {prerelease}, {rcn}, {buildmetadata}. "
                "Wrap in [] for optional sections."
            ),
            "ui_type": "string",
            "ui_example": (
                "[{major}][.{minor}][.{patch}][.{hotfix}]"
                "[-{prerelease}][.{rcn}][+{buildmetadata}]"
            ),
        },
    )
    extra_info: bool = field(
        default=False,
        metadata={
            "ui_desc": "Include host/environment information during stamping.",
            "ui_type": "bool",
        },
    )
    create_verinfo_files: bool = field(
        default=False,
        metadata={
            "ui_desc": (
                "Create a version info file per stamp. "
                "Enables 'vmn show --from-file' without git tags."
            ),
            "ui_type": "bool",
        },
    )
    hide_zero_hotfix: bool = field(
        default=True,
        metadata={
            "ui_desc": (
                "Hide the hotfix octet when it equals zero "
                "(e.g. 1.2.3 instead of 1.2.3.0)."
            ),
            "ui_type": "bool",
        },
    )
    version_backends: dict = field(
        default_factory=dict,
        metadata={
            "ui_desc": (
                "Auto-embed version into files during stamping. "
                "Backends: npm, cargo, poetry, pep621, generic_jinja, "
                "generic_selectors."
            ),
            "ui_type": "nested_dict",
            "ui_editor": "version_backends",
        },
    )
    deps: dict = field(
        default_factory=dict,
        metadata={
            "attr": "raw_configured_deps",
            "ui_desc": (
                "External repository dependencies tracked during stamping. "
                "vmn auto-detects remote URLs from existing git repos."
            ),
            "ui_type": "nested_dict",
            "ui_editor": "deps",
        },
    )
    policies: dict = field(
        default_factory=dict,
        metadata={
            "ui_desc": (
                "Enforce policies during stamping/releasing. "
                "Supports whitelist_release_branches."
            ),
            "ui_type": "nested_dict",
            "ui_editor": "policies",
        },
    )
    conventional_commits: dict = field(
        default_factory=dict,
        metadata={
            "ui_desc": (
                "Enable automatic release mode detection from conventional "
                "commit messages. Works with default_release_mode."
            ),
            "ui_type": "bool_or_dict",
        },
    )
    default_release_mode: str = field(
        default="optional",
        metadata={
            "ui_desc": (
                "How conventional commits determine release mode. "
                "'optional' uses --orm behavior, 'strict' uses -r behavior."
            ),
            "ui_type": "choice",
            "ui_choices": ["optional", "strict"],
        },
    )
    changelog: dict = field(
        default_factory=dict,
        metadata={
            "ui_desc": (
                "Changelog generation settings. "
                "Set 'path' to the output file for automatic changelogs."
            ),
            "ui_type": "nested_dict",
        },
    )
    github_release: dict = field(
        default_factory=dict,
        metadata={
            "ui_desc": (
                "GitHub Release creation settings. "
                "Automatically creates a GitHub release on stamp."
            ),
            "ui_type": "nested_dict",
        },
    )

    def __post_init__(self):
        if not self.template:
            self.template = _DEFAULT_TEMPLATE

    @classmethod
    def conf_key_to_attr(cls):
        """Return {conf_yml_key: self_attr_name} for all fields."""
        return {
            f.name: f.metadata.get("attr", f.name) for f in fields(cls)
        }

    @classmethod
    def config_descriptions(cls):
        """Build the _CONFIG_DESCRIPTIONS dict from field metadata."""
        descs = {}
        for f in fields(cls):
            if "ui_desc" not in f.metadata:
                continue
            entry = {
                "description": f.metadata["ui_desc"],
                "type": f.metadata["ui_type"],
            }
            if "ui_example" in f.metadata:
                entry["example"] = f.metadata["ui_example"]
            if "ui_choices" in f.metadata:
                entry["choices"] = f.metadata["ui_choices"]
            if f.metadata["ui_type"] == "nested_dict":
                entry["nested_key"] = f.name
                if "ui_editor" in f.metadata:
                    entry["ui_editor"] = f.metadata["ui_editor"]
            descs[f.name] = entry
        return descs

    @classmethod
    def default_conf_dict(cls):
        """Build the VMN_DEFAULT_CONF dict from dataclass defaults."""
        d = asdict(cls())
        d["old_template"] = VMN_OLD_TEMPLATE
        return d


VMN_DEFAULT_CONF = AppConf.default_conf_dict()
