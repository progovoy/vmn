import argparse
import os
import subprocess
import sys


def atomic_push(branch=None, tags=None):
    if tags is None:
        tags = []
    if branch:
        subprocess.check_call(["git", "push", "origin", branch])
    for tag in tags:
        subprocess.check_call(["git", "push", "origin", f"refs/tags/{tag}"])


def get_head_tag():
    tags = (
        subprocess.check_output(["git", "tag", "--points-at", "HEAD"]).decode().split()
    )
    return tags[0] if tags else None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--stamp", action="store_true")
    parser.add_argument("-v", "--version", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.stamp and args.version:
        parser.error("--stamp conflicts with -v")

    branch = (
        subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        .decode()
        .strip()
    )
    allowed = os.environ.get("RELEASE_BRANCHES")
    if allowed:
        allowed_set = {b.strip() for b in allowed.split(",") if b.strip()}
        if branch not in allowed_set:
            return 1

    tag = get_head_tag()
    if args.version is None:
        if not tag or "-" not in tag:
            return 1
        args.version = tag.split("-")[0]

    try:
        if args.stamp and not args.dry_run:
            subprocess.check_call([
                "git",
                "commit",
                "--allow-empty",
                "-m",
                f"Release {args.version}",
            ])
        if not args.dry_run:
            subprocess.check_call(["git", "tag", args.version])
            atomic_push(branch if args.stamp else None, [args.version])
    except Exception as exc:
        print("EXC", exc)
        if not args.dry_run:
            subprocess.call(["git", "tag", "-d", args.version])
            if args.stamp:
                subprocess.call(["git", "reset", "--hard", "HEAD~1"])
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
