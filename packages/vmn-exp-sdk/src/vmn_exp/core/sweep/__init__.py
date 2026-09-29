"""Server-less hyperparameter sweeps (``vmn-exp sweep``), W&B-Sweeps style.

A sweep is an outer experiment run whose metadata carries the spec
(:mod:`.spec`). Agents claim trial slots atomically in storage
(:mod:`.claims`), draw the trial's params (:mod:`.suggest`), run it as an inner
job, and may stop it early (:mod:`.early_stop`). :mod:`.summary` folds the
trial rows into ``vmn-exp sweep status``. No server: storage is the only
coordination point, so agents on Slurm/k8s sharing an NFS dir or a bucket work.
"""
