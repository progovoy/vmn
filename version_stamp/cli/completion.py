#!/usr/bin/env python3
"""Shell completion support for vmn using argcomplete."""
import os
import sys


def _find_vmn_root():
    """Walk up from cwd to find the directory containing .vmn/."""
    path = os.environ.get("VMN_WORKING_DIR", os.getcwd())
    while True:
        if os.path.isdir(os.path.join(path, ".vmn")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def app_name_completer(prefix, parsed_args, **kwargs):
    """Complete app names by scanning .vmn/ for last_known_app_version.yml files."""
    root = _find_vmn_root()
    if root is None:
        return []

    vmn_dir = os.path.join(root, ".vmn")
    ver_filename = "last_known_app_version.yml"
    apps = []

    for dirpath, dirnames, filenames in os.walk(vmn_dir):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in ("branch_conf", "snapshots", "experiments")
        ]
        if ver_filename in filenames:
            rel = os.path.relpath(dirpath, vmn_dir)
            app_name = rel.replace(os.sep, "/")
            apps.append(app_name)

    return [a for a in apps if a.startswith(prefix)]


def setup_completion(parser):
    """Activate argcomplete on the parser and attach app-name completers."""
    try:
        import argcomplete
    except ImportError:
        return

    for action in parser._subparsers._actions:
        if not hasattr(action, "_parser_class"):
            continue
        for subparser in action.choices.values():
            for sub_action in subparser._actions:
                if sub_action.dest == "name" and not sub_action.option_strings:
                    sub_action.completer = app_name_completer

    argcomplete.autocomplete(parser)


COMPLETION_SCRIPTS = {
    "bash": 'eval "$(register-python-argcomplete vmn)"',
    "zsh": (
        "autoload -U bashcompinit\n"
        "bashcompinit\n"
        'eval "$(register-python-argcomplete vmn)"'
    ),
    "fish": "register-python-argcomplete --shell fish vmn | source",
    "tcsh": "eval `register-python-argcomplete --shell tcsh vmn`",
}

SETUP_INSTRUCTIONS = {
    "bash": "# Add to ~/.bashrc:\n{script}",
    "zsh": "# Add to ~/.zshrc:\n{script}",
    "fish": "# Add to ~/.config/fish/config.fish:\n{script}",
    "tcsh": "# Add to ~/.tcshrc:\n{script}",
}


def print_completion_setup(shell=None):
    """Print shell completion setup instructions."""
    if shell is None:
        shell = _detect_shell()

    if shell not in COMPLETION_SCRIPTS:
        print(f"Unsupported shell: {shell}", file=sys.stderr)
        print(f"Supported shells: {', '.join(COMPLETION_SCRIPTS.keys())}", file=sys.stderr)
        return 1

    script = COMPLETION_SCRIPTS[shell]
    instructions = SETUP_INSTRUCTIONS[shell].format(script=script)
    print(instructions)
    return 0


RC_FILES = {
    "bash": os.path.expanduser("~/.bashrc"),
    "zsh": os.path.expanduser("~/.zshrc"),
    "fish": os.path.expanduser("~/.config/fish/config.fish"),
    "tcsh": os.path.expanduser("~/.tcshrc"),
}


def install_completion(shell=None):
    """Append completion setup to the user's shell rc file."""
    if shell is None:
        shell = _detect_shell()

    if shell not in COMPLETION_SCRIPTS:
        print(f"Unsupported shell: {shell}", file=sys.stderr)
        print(f"Supported shells: {', '.join(COMPLETION_SCRIPTS.keys())}", file=sys.stderr)
        return 1

    rc_path = RC_FILES[shell]
    script = COMPLETION_SCRIPTS[shell]

    if os.path.exists(rc_path):
        with open(rc_path, "r") as f:
            content = f.read()
        if "register-python-argcomplete vmn" in content:
            print(f"Completion already installed in {rc_path}")
            return 0

    os.makedirs(os.path.dirname(rc_path), exist_ok=True)
    with open(rc_path, "a") as f:
        f.write(f"\n# vmn shell completion\n{script}\n")

    print(f"Completion installed in {rc_path}")
    print(f"Restart your shell or run: source {rc_path}")
    return 0


def _detect_shell():
    """Best-effort detection of the user's shell."""
    shell_path = os.environ.get("SHELL", "")
    basename = os.path.basename(shell_path)
    if basename in COMPLETION_SCRIPTS:
        return basename
    return "bash"
