"""``vmn-exp settings <app> [show|set -f <file>]`` (plan 28 A0): the app's
store settings (:mod:`vmn_exp.core.app_settings`). Git-free, like
``vmn-exp model``."""
import sys

from vmn_exp.core.app_settings import SettingsError
from vmn_exp.core.app_settings_store import read_settings_text, write_settings
from vmn_exp.registry.cli import _get_storage
from vmn_exp.registry.cli_parser import _add_storage_args


def add_settings_parser(subparsers):
    parser = subparsers.add_parser("settings", help="Show or set an app's store settings")
    parser.set_defaults(strict_version=False)
    parser.add_argument("name", help="App name")
    parser.add_argument("action", nargs="?", choices=("show", "set"), default="show",
                        help="show (default) prints the file; set replaces it")
    parser.add_argument("-f", "--file", help="The settings YAML to set ('-' reads stdin)")
    _add_storage_args(parser)
    return parser


def settings_run_without_repo(args):
    storage = _get_storage(args)
    if args.action == "set":
        return _set(storage, args)
    text = read_settings_text(storage, args.name)
    if text is None:
        print(f"No settings for {args.name}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def _read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path) as f:
        return f.read()


def _set(storage, args):
    if not args.file:
        print("settings set needs -f <file>", file=sys.stderr)
        return 1
    try:
        write_settings(storage, args.name, _read(args.file))
    except OSError as exc:
        print(f"Cannot read {args.file}: {exc}", file=sys.stderr)
        return 1
    except SettingsError as exc:
        print(f"Invalid settings: {exc}", file=sys.stderr)
        return 1
    print(f"Set the store settings of {args.name}")
    return 0
