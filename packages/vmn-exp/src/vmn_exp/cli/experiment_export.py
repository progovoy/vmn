"""``vmn-exp restore``, ``export`` and ``prune``.

``_resolve_experiment_version`` is looked up on :mod:`vmn_exp.cli.experiment`
at call time, so a test's patch there still reaches these commands (plan 44
G15)."""
import os
import shutil

import yaml

from vmn_exp.cli.code_record import load_code_record
from vmn_exp.cli.prune import experiment_prune as _experiment_prune
from vmn_exp.cli.provenance import refuse_no_code
from vmn_exp.core.identity import known_identity
from vmn_exp.core.log import load_log
from vmn_exp.core.snapshot_features import EXPERIMENT_FILE, write_features_file
from vmn_exp.snapshot import _restore_with_safety_net
from vmn_exp.storage.files import FILE_TREES, safe_verstr
from version_stamp.api import VMN_LOGGER, export_tree, measure_runtime_decorator


@measure_runtime_decorator
def experiment_restore(vcs, params, storage, args, clock):
    from vmn_exp.cli import experiment as _exp

    verstr, err = _exp._resolve_experiment_version(storage, vcs, args, default_latest=True)
    if err:
        VMN_LOGGER.error(err)
        return 1

    record = load_code_record(
        vcs, params, verstr, app_name=_exp._app_name(vcs, args), exp_storage=storage,
        clock=clock)
    if record is None:
        return 1
    return _restore_with_safety_net(vcs, dict(params, force=args.force), *record)


@measure_runtime_decorator
def experiment_export(vcs, params, storage, args, console):
    from vmn_exp.cli import experiment as _exp

    verstr, err = _exp._resolve_experiment_version(storage, vcs, args, default_latest=True)
    if err:
        VMN_LOGGER.error(err)
        return 1

    app_name = _exp._app_name(vcs, args)
    metadata, patches = storage.load(app_name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return 1

    rc = refuse_no_code(metadata, action="export")
    if rc is not None:
        return rc

    log = load_log(storage, app_name, verstr)
    # Who exported: a git-free run of the tree may name no one else.
    exported_by = known_identity(vcs.backend.repo_path)

    def write_experiment_files(dest):
        with open(os.path.join(dest, EXPERIMENT_FILE), "w") as f:
            yaml.dump({"metadata": metadata, "log": log, "exported_by": exported_by},
                      f, sort_keys=False)
        write_features_file(dest, log, exported_by)
        record_dir = storage.local_record_dir(app_name, verstr)
        for tree in FILE_TREES if record_dir else ():
            src = os.path.join(record_dir, tree)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(dest, tree), dirs_exist_ok=True)

    output_path, err = export_tree(
        vcs, (metadata, patches), safe_verstr(verstr), args.output,
        write_experiment_files,
    )
    if err:
        return err
    console.out(output_path)
    return 0


@measure_runtime_decorator
def experiment_prune(vcs, params, storage, args, clock):
    from vmn_exp.cli import experiment as _exp

    return _experiment_prune(vcs, params, storage, args, _exp._app_name(vcs, args), clock)
