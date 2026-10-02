"""``vmn-exp migrate [--store <uri> | --dir <path>] [--dry-run] [--skip-live]``:
convert a v1 store to layout 2 (docs/plans/14-store-layout.md §4).

``store.yml`` gets ``migrating: true`` first (writers refuse from then on);
then each record is copied to its v2 path (converted by
:data:`~vmn_exp.cli.migrate_convert.RECORD_CONVERTERS`, ``metadata.yml``
last) and its old copy deleted. A record whose v2 ``metadata.yml`` exists is
done, so a killed migration resumes. Finally ``migrating`` is cleared.
"""
import argparse
import sys

import yaml

from vmn_exp.cli.migrate_convert import convert_record
from vmn_exp.cli.migrate_records import (
    METADATA, classify, local_records, object_records, v2_prefix,
)
from vmn_exp.cli.migrate_tree import LocalTree, ObjectTree
from vmn_exp.core.status import RUN_STATE_FILE, RUNNING, STUCK, derive_status
from vmn_exp.storage import areas
from vmn_exp.storage.store_marker import MARKER, LAYOUT, forget_checked, new_marker

_V1_PREFIXES = (("vmn-experiments", areas.RUNS), ("vmn-snapshots", areas.SNAPSHOTS))
_V1_LOCAL = ".vmn"


def _parser():
    p = argparse.ArgumentParser(prog="vmn-exp migrate",
                                description="Convert a v1 store to store layout 2")
    where = p.add_mutually_exclusive_group()
    where.add_argument("--store", help="store URI (s3://, gs://, az://, file://)")
    where.add_argument("--dir", help="a local store dir (v1: records under <dir>/.vmn)")
    p.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    p.add_argument("--skip-live", action="store_true",
                   help="leave running/stuck runs for a later rerun")
    return p


def run_migrate(argv):
    args = _parser().parse_args(argv)
    opts = dict(dry_run=args.dry_run, skip_live=args.skip_live)
    if args.dir:
        return migrate_local(args.dir, "", **opts)
    if not args.store:
        from vmn_exp._base import resolve_root_path

        return migrate_local(resolve_root_path(), ".vmn/store", gitignore=True, **opts)
    from vmn_exp.storage.registry import open_store
    from vmn_exp.storage.uri import parse_store_uri

    uri = parse_store_uri(args.store)
    if uri.scheme == "file":
        return migrate_local(uri.path, "", **opts)
    raw = open_store(uri, area=areas.RUNS)
    return migrate_objects(raw._s3, raw.bucket, uri.path, **opts)


def migrate_local(base, root, dry_run=False, skip_live=False, gitignore=False):
    """Migrate the v1 records below ``<base>/.vmn`` to the v2 root ``<base>/<root>``."""
    tree = LocalTree(base)
    records, containers = local_records(tree, _V1_LOCAL, skip=root or None)
    code = _migrate(tree, root, records, dry_run, skip_live)
    if code or dry_run:
        return code
    for container in sorted(containers, reverse=True):
        tree.prune_container(container, _V1_LOCAL)
    if gitignore and tree.read(_key(root, ".gitignore")) is None:
        tree.write(_key(root, ".gitignore"), b"*\n")
    return 0


def migrate_objects(client, bucket, path, dry_run=False, skip_live=False):
    """Migrate a v1 object store: under *path*, else the v1 default prefixes."""
    tree = ObjectTree(client, bucket)
    if path:
        records = object_records(tree, path, None)
    else:
        records = [r for prefix, area in _V1_PREFIXES
                   for r in object_records(tree, prefix, area)]
    return _migrate(tree, path or areas.DEFAULT_ROOT, records, dry_run, skip_live)


def _key(root, name):
    return f"{root}/{name}" if root else name


def _is_live(tree, record):
    if record.area != areas.RUNS or RUN_STATE_FILE not in record.names:
        return False
    state = yaml.safe_load(tree.read(f"{record.src}/{RUN_STATE_FILE}") or b"")
    return isinstance(state, dict) and derive_status(state) in (RUNNING, STUCK)


def _migrate(tree, root, records, dry_run, skip_live):
    for record in records:
        classify(record, tree.read(f"{record.src}/{METADATA}"))
    live = [r for r in records if _is_live(tree, r)]
    if live and not skip_live:
        print("vmn-exp migrate: running or stuck runs (finish them, or pass "
              "--skip-live):\n" + "".join(f"  {r.scope} {r.name}\n" for r in live),
              file=sys.stderr, end="")
        return 1
    todo = [r for r in records if r not in live]
    if dry_run:
        for r in todo:
            print(f"{r.src} -> {v2_prefix(root, r)}")
        return 0
    _write_marker(tree, root, migrating=True)
    for record in todo:
        migrate_record(tree, root, record)
    _write_marker(tree, root, migrating=False)
    forget_checked()
    print(f"migrated {len(todo)} records, skipped {len(live)} live runs")
    return 0


def _write_marker(tree, root, migrating):
    text = tree.read(_key(root, MARKER))
    marker = (yaml.safe_load(text) if text else None) or new_marker()
    marker["layout"] = LAYOUT
    if migrating:
        marker["migrating"] = True
    else:
        marker.pop("migrating", None)
    tree.write(_key(root, MARKER), yaml.safe_dump(marker, sort_keys=False).encode())


def migrate_record(tree, root, record):
    """Copy *record* to its v2 place (unless done), then delete its old copy."""
    dst = v2_prefix(root, record)
    if tree.read(f"{dst}/{METADATA}") is None:
        if METADATA not in record.names:
            print(f"vmn-exp migrate: skipping {record.src} (no {METADATA})",
                  file=sys.stderr)
            return
        files = convert_record(record.names, lambda s: _bytes(tree, record, s))
        metadata = files.pop(METADATA)
        for name, source in [*files.items(), (METADATA, metadata)]:
            _put(tree, record, f"{dst}/{name}", source)
    tree.delete_prefix(record.src)


def _bytes(tree, record, source):
    return source if isinstance(source, bytes) else tree.read(f"{record.src}/{source}")


def _put(tree, record, key, source):
    if isinstance(source, bytes):
        tree.write(key, source)
    else:
        tree.transfer(f"{record.src}/{source}", key)
