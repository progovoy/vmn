"""``vmn snapshot export``: a snapshot's tree as a plain directory or tarball.

The tree is materialized from the local repo when it has the base commit (the
record's remote otherwise), the snapshot's patches and deps applied, every
``.git`` stripped, and ``vmn_metadata.yml`` written at its root. An output
ending in ``.tar.gz``/``.tgz`` is a tarball of ``<verstr>/``; the default is
``<verstr>.tar.gz`` in the current directory. Prints the output path.

Public: ``snapshot_export(vcs, stores, verstr, output_path=None) -> int``;
``export_tree(vcs, record, name, output_path=None, write_extra=None)
-> (output_path, err)`` (shared with ``vmn-exp export``).
"""
import os
import shutil
import tarfile
import tempfile

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.materialize import _materialize_workdir, _strip_git_dirs
from version_stamp.snapshot.load import load_snapshot
from version_stamp.snapshot.record import safe_verstr

_TARBALL_SUFFIXES = (".tar.gz", ".tgz")


def _export_dir(vcs, record, dest, write_extra):
    existed = os.path.exists(dest)
    err = _materialize_workdir(vcs, *record, dest)
    if not err:
        _strip_git_dirs(dest)
        if write_extra:
            write_extra(dest)
    elif not existed:
        shutil.rmtree(dest, ignore_errors=True)
    return err


def _export_tarball(vcs, record, output_path, name, write_extra):
    tmpdir = tempfile.mkdtemp(prefix="vmn-export-")
    try:
        dest = os.path.join(tmpdir, name)
        err = _export_dir(vcs, record, dest, write_extra)
        if not err:
            with tarfile.open(output_path, "w:gz") as tar:
                tar.add(dest, arcname=name)
        return err
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def export_tree(vcs, record, name, output_path=None, write_extra=None):
    """Export *record*'s tree to *output_path* (default ``<name>.tar.gz``).

    ``write_extra(dest)`` adds files to the materialized tree before it is
    archived. ``(output_path, error code or None)``.
    """
    output_path = output_path or f"{name}.tar.gz"
    if output_path.endswith(_TARBALL_SUFFIXES):
        err = _export_tarball(vcs, record, output_path, name, write_extra)
    else:
        err = _export_dir(vcs, record, output_path, write_extra)
    return output_path, err


def snapshot_export(vcs, stores, verstr, output_path=None):
    record = load_snapshot(stores, vcs.name, verstr, "export")
    if record is None:
        return 1
    output_path, err = export_tree(vcs, record, safe_verstr(verstr), output_path)
    if err:
        return err
    VMN_LOGGER.info(f"Exported snapshot {verstr} to {output_path}")
    print(output_path)
    return 0
