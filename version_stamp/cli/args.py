#!/usr/bin/env python3
"""CLI argument parsing."""
import argparse
import sys

from version_stamp import version as version_mod
from version_stamp.backends.base import VMNBackend
from version_stamp.core.constants import (
    SEMVER_BUILDMETADATA_REGEX,
    VMN_VERSION_FORMAT,
    VMN_VERSTR_REGEX,
)
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.cli.constants import VMN_ARGS


def parse_user_commands(command_line):
    parser = argparse.ArgumentParser("vmn")
    parser.add_argument(
        "--version", "-v", action="version", version=version_mod.version
    )
    parser.add_argument("--debug", required=False, action="store_true")
    parser.set_defaults(debug=False)
    subprasers = parser.add_subparsers(dest="command")

    for arg in VMN_ARGS.keys():
        arg = arg.replace("-", "_")
        getattr(sys.modules[__name__], f"add_arg_{arg}")(subprasers)

    args = parser.parse_args(command_line)

    verify_user_input_version(args, "version")
    verify_user_input_version(args, "ov")
    verify_user_input_version(args, "orv")

    return args


def add_arg_gen(subprasers):
    pgen = subprasers.add_parser(
        "gen", help="Generate version file based on jinja2 template"
    )
    pgen.add_argument(
        "-v",
        "--version",
        default=None,
        required=False,
        help=f"The version to generate the file for in the format:"
        f" {VMN_VERSION_FORMAT}",
    )
    pgen.add_argument(
        "-t", "--template", required=True, help="Path to the jinja2 template"
    )
    pgen.add_argument("-o", "--output", required=True, help="Path for the output file")
    pgen.add_argument("--verify-version", dest="verify_version", action="store_true")
    pgen.set_defaults(verify_version=False)
    pgen.add_argument("name", help="The application's name")
    pgen.add_argument(
        "-c",
        "--custom-values",
        default=None,
        required=False,
        help="Path to a yml file with custom keys and values",
    )


def add_arg_release(subprasers):
    prelease = subprasers.add_parser("release", help="Release app version")
    group = prelease.add_mutually_exclusive_group()
    group.add_argument(
        "-v",
        "--version",
        default=None,
        required=False,
        help=f"The version to release in the format: "
        f" {VMN_VERSION_FORMAT}",
    )
    group.add_argument("-s", "--stamp", dest="stamp", action="store_true")
    prelease.set_defaults(stamp=False)
    prelease.add_argument("name", help="The application's name")


def add_arg_goto(subprasers):
    pgoto = subprasers.add_parser("goto", help="go to version")
    pgoto.add_argument(
        "-v",
        "--version",
        default=None,
        required=False,
        help=f"The version to go to in the format: "
        f" {VMN_VERSION_FORMAT}",
    )
    pgoto.add_argument("--root", dest="root", action="store_true")
    pgoto.set_defaults(root=False)
    pgoto.add_argument("--deps-only", dest="deps_only", action="store_true")
    pgoto.set_defaults(deps_only=False)
    pgoto.add_argument("name", help="The application's name")
    pgoto.add_argument("--pull", dest="pull", action="store_true")
    pgoto.set_defaults(pull=False)


def add_arg_stamp(subprasers):
    pstamp = subprasers.add_parser("stamp", help="stamp version")
    pstamp.add_argument(
        "-r",
        "--release-mode",
        choices=["major", "minor", "patch", "hotfix", "micro"],
        default=None,
        help="major / minor / patch / hotfix",
        metavar="",
    )
    pstamp.add_argument(
        "--orm",
        "--optional-release-mode",
        choices=["major", "minor", "patch", "hotfix"],
        default=None,
        help="major / minor / patch / hotfix",
        metavar="",
    )
    pstamp.add_argument(
        "--pr",
        "--prerelease",
        default=None,
        help="Prerelease version. Can be anything really until you decide "
        "to release the version",
    )
    pstamp.add_argument("--pull", dest="pull", action="store_true")
    pstamp.set_defaults(pull=False)
    pstamp.add_argument(
        "--dont-check-vmn-version", dest="check_vmn_version", action="store_false"
    )
    pstamp.set_defaults(check_vmn_version=True)
    pstamp.add_argument(
        "--orv",
        "--override-root-version",
        default=None,
        help="Override current root version with any integer of your choice",
    )
    pstamp.add_argument(
        "--ov",
        "--override-version",
        default=None,
        help=f"Override current version with any version in the "
        f"format: {VMN_VERSTR_REGEX}",
    )
    pstamp.add_argument("--dry-run", dest="dry", action="store_true")
    pstamp.set_defaults(dry=False)
    pstamp.add_argument("name", help="The application's name")
    pstamp.add_argument(
        "-e",
        "--extra-commit-message",
        default="",
        help="add more information to the commit message."
        "example: adding --extra-commit-message '[ci-skip]' "
        "will add the string '[ci-skip]' to the commit message",
    )


def add_arg_show(subprasers):
    pshow = subprasers.add_parser("show", help="show app version")
    pshow.add_argument("name", help="The application's name to show the version for")
    pshow.add_argument(
        "-v",
        "--version",
        default=None,
        help=f"The version to show. Must be specified in the raw version format:"
        f" {VMN_VERSION_FORMAT}",
    )
    pshow.add_argument(
        "-t", "--template", default=None, help="The template to use in show"
    )
    pshow.add_argument("--root", dest="root", action="store_true")
    pshow.set_defaults(root=False)
    pshow.add_argument("--verbose", dest="verbose", action="store_true")
    pshow.set_defaults(verbose=False)
    pshow.add_argument("--conf", dest="conf", action="store_true")
    pshow.set_defaults(conf=False)
    pshow.add_argument("--raw", dest="raw", action="store_true")
    pshow.set_defaults(raw=False)
    pshow.add_argument("--from-file", dest="from_file", action="store_true")
    pshow.set_defaults(from_file=False)
    pshow.add_argument("--ignore-dirty", dest="ignore_dirty", action="store_true")
    pshow.set_defaults(ignore_dirty=False)
    pshow.add_argument("-u", "--unique", dest="display_unique_id", action="store_true")
    pshow.set_defaults(display_unique_id=False)
    pshow.add_argument("--type", dest="display_type", action="store_true")
    pshow.set_defaults(display_type=False)
    pshow.add_argument("--dev", dest="dev", action="store_true")
    pshow.set_defaults(dev=False)


def add_arg_init_app(subprasers):
    pinitapp = subprasers.add_parser(
        "init-app",
        help="initialize version tracking for application. "
        "This command should be called only once per application",
    )

    pinitapp.add_argument(
        "-v",
        "--version",
        default="0.0.0",
        help="The version to init from. Must be specified in the raw version format: "
        "{major}.{minor}.{patch}",
    )
    pinitapp.add_argument("--dry-run", dest="dry", action="store_true")
    pinitapp.set_defaults(dry=False)
    pinitapp.add_argument(
        "--orm",
        "--default-release-mode",
        dest="orm",
        choices=["optional", "strict"],
        default="optional",
        help="Set the default_release_mode for the app config. "
        "'optional' uses --orm behavior, 'strict' uses -r behavior. "
        "Default: optional",
    )
    pinitapp.add_argument(
        "name", help="The application's name to initialize version tracking for"
    )


def add_arg_init(subprasers):
    subprasers.add_parser(
        "init",
        help="initialize version tracking for the repository. "
        "This command should be called only once per repository",
    )


def add_arg_add(subprasers):
    padd = subprasers.add_parser(
        "add", help="Add additional metadata for already stamped version"
    )
    padd.add_argument(
        "-v",
        "--version",
        default=None,
        required=False,
        help=f"The version to add the 'buildmetadata' in the format:"
        f" {VMN_VERSION_FORMAT}",
    )
    padd.add_argument(
        "--bm",
        "--buildmetadata",
        required=True,
        help=f"String for the 'buildmetadata' version extension "
        f"without the '+' sign complying with the regex:"
        f" {SEMVER_BUILDMETADATA_REGEX}",
    )
    padd.add_argument(
        "--vmp",
        "--version-metadata-path",
        required=False,
        help="A path to a YML file which is associated with the specific build version",
    )
    padd.add_argument(
        "--vmu",
        "--version-metadata-url",
        required=False,
        help="A URL which is associated with the specific build version",
    )
    padd.add_argument("name", help="The application's name")


def add_arg_config(subprasers):
    pconfig = subprasers.add_parser(
        "config",
        help="View and edit application configuration interactively",
    )
    pconfig.add_argument(
        "name",
        nargs="?",
        default=None,
        help="The application name. If omitted, lists all managed apps.",
    )
    pconfig.add_argument(
        "--vim",
        dest="vim",
        action="store_true",
        help="Open the config file in $EDITOR (default: vim) instead of the TUI",
    )
    pconfig.set_defaults(vim=False)
    pconfig.add_argument(
        "--root",
        dest="root",
        action="store_true",
        help="Edit the root app config (root_conf.yml) instead of per-app conf.yml",
    )
    pconfig.set_defaults(root=False)
    pconfig.add_argument(
        "--global",
        dest="global_conf",
        action="store_true",
        help="Edit the repo-level .vmn/conf.yml",
    )
    pconfig.set_defaults(global_conf=False)
    pconfig.add_argument(
        "--branch",
        dest="branch",
        action="store_true",
        help="Edit the branch-specific config (<current-branch>_conf.yml) instead of the default",
    )
    pconfig.set_defaults(branch=False)


def add_arg_snapshot(subprasers):
    psnap = subprasers.add_parser(
        "snapshot",
        help="Create and manage local snapshots of uncommitted/unpushed changes",
    )
    psnap.add_argument(
        "action",
        nargs="?",
        default="create",
        choices=["create", "list", "show", "note", "diff", "export"],
        help="Snapshot action: create (default), list, show, note, diff, export",
    )
    psnap.add_argument("name", help="The application's name")
    psnap.add_argument(
        "-v",
        "--version",
        default=None,
        required=False,
        help="The dev version string (for show/note/diff/export actions)",
    )
    psnap.add_argument(
        "--note",
        default=None,
        required=False,
        help="A description note for the snapshot",
    )
    psnap.add_argument(
        "--backend",
        default="local",
        choices=["local", "s3"],
        help="Storage backend for snapshots (default: local)",
    )
    psnap.add_argument(
        "--bucket",
        default=None,
        required=False,
        help="S3 bucket name (required for s3 backend)",
    )
    psnap.add_argument(
        "--endpoint-url",
        default=None,
        required=False,
        help="Custom S3 endpoint URL (for MinIO, DigitalOcean Spaces, etc.)",
    )
    psnap.add_argument(
        "--prefix",
        default="vmn-snapshots",
        required=False,
        help="S3 key prefix for snapshot storage (default: vmn-snapshots)",
    )
    psnap.add_argument(
        "--to",
        default=None,
        required=False,
        help="Second version for diff comparison (or 'current' for working state)",
    )
    psnap.add_argument(
        "--tool",
        default=None,
        required=False,
        help="External diff tool (e.g., bcompare, meld, vimdiff). Falls back to git config diff.tool",
    )
    psnap.add_argument(
        "-o",
        "--output",
        default=None,
        required=False,
        help="Output path for export (default: {verstr}.tar.gz)",
    )
    psnap.add_argument(
        "--meta",
        action="append",
        default=None,
        required=False,
        help="Key=value metadata pair (can be specified multiple times)",
    )
    psnap.add_argument(
        "--meta-file",
        default=None,
        required=False,
        help="Path to YAML file containing metadata key-value pairs",
    )
    psnap.add_argument(
        "--filter",
        action="append",
        default=None,
        required=False,
        help="Filter snapshots by key=value metadata (for list action, can be repeated)",
    )
    psnap.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Show full ISO timestamps in list output",
    )
    psnap.add_argument(
        "--latest",
        action="store_true",
        default=False,
        help="Use the most recent snapshot (for show/note/diff/export)",
    )


def _add_experiment_parser(subprasers, name):
    pexp = subprasers.add_parser(name, help="Experiment tracking for reproducible research")
    pexp.add_argument(
        "action",
        nargs="?",
        default="create",
        choices=["create", "add", "list", "show", "compare", "restore", "export", "prune"],
        help="Experiment action (default: create)",
    )
    pexp.add_argument("name", help="The application's name")
    pexp.add_argument(
        "-v", "--version",
        action="append",
        default=None,
        help="Version string(s). Repeatable for compare.",
    )
    pexp.add_argument("--note", default=None, help="Note or description")
    pexp.add_argument(
        "-f", "--file",
        default=None,
        help="YAML file with structured notes/params",
    )
    pexp.add_argument(
        "--metrics",
        nargs="*",
        default=None,
        help="Metrics as key=value pairs (e.g., loss=0.34 acc=0.91)",
    )
    pexp.add_argument("--attach", default=None, help="File to attach as artifact")
    pexp.add_argument("--sort", default=None, help="Sort list by metric name")
    pexp.add_argument("--top", type=int, default=None, help="Show top N results in list")
    pexp.add_argument(
        "--latest",
        action="store_true",
        default=False,
        help="Use the most recent experiment (for show/compare/restore/export)",
    )
    pexp.add_argument("--tool", default=None, help="External diff tool for compare. Falls back to git config diff.tool")
    pexp.add_argument("-o", "--output", default=None, help="Output path for export")
    pexp.add_argument("--keep", type=int, default=None, help="Keep latest N experiments (for prune)")
    pexp.add_argument("--older-than", default=None, help="Prune experiments older than duration (e.g., 30d)")
    pexp.add_argument(
        "--backend",
        default="local",
        choices=["local", "s3"],
        help="Storage backend (default: local)",
    )
    pexp.add_argument("--bucket", default=None, help="S3 bucket name")
    pexp.add_argument("--endpoint-url", default=None, help="Custom S3 endpoint URL")
    pexp.add_argument("--prefix", default="vmn-experiments", help="S3 key prefix")


def add_arg_experiment(subprasers):
    _add_experiment_parser(subprasers, "experiment")


def add_arg_exp(subprasers):
    _add_experiment_parser(subprasers, "exp")


def verify_user_input_version(args, key):
    if key not in args or getattr(args, key) is None:
        return

    val = getattr(args, key)
    if isinstance(val, list):
        return

    try:
        props = VMNBackend.deserialize_vmn_version(val)
    except Exception:
        if "root" not in args or not args.root:
            err = f"Version must be in format: {VMN_VERSION_FORMAT}"
        else:
            err = "Root version must be an integer"

        VMN_LOGGER.error(err)

        raise RuntimeError(err)

    if props.buildmetadata is not None:
        if key == "ov":
            err = f"Option: {key} must not include buildmetadata parts"
            VMN_LOGGER.error(err)
            raise RuntimeError(err)

