"""What the flat experiment parser makes of real command lines (plan 39 B5a).

The corpus comes from docs/vmn-exp/experiments.md, client-guide.md and
cli/skill.py. Each line lists the attributes it sets away from the bare
``<action> my_app`` parse; the defaults are pinned once, so moving the flags
into groups can't change what any command parses to.
"""
import shlex

import pytest

from version_stamp.cli.args import parse_user_commands
from vmn_exp.cli.exp_parser.actions import ACTION_FLAGS
from vmn_exp.cli.exp_parser.build import flag_defaults
from vmn_exp.cli.exp_parser.ownership import foreign_flags
from vmn_exp.cli.plugin import register_all

CORPUS = [
    ('create my_app --note "batch=128" -f variant.yml --metrics latency_ms=15.1',
     {"note": "batch=128", "file": "variant.yml", "metrics": ["latency_ms=15.1"]}),
    ('create my_app --parent @2 --input "train=s3://bucket/train.csv#sha256:abc"',
     {"inputs": ["train=s3://bucket/train.csv#sha256:abc"], "parent": "@2"}),
    ("create my_app -f params.yml --name baseline-v1",
     {"run_name": "baseline-v1", "file": "params.yml"}),
    ("run my_app --fork-from @7 --fork-step 500 -- python train.py --lr 1e-4 --resume-step 500",
     {"fork_from": "@7", "fork_step": 500,
      "run_cmd": ["python", "train.py", "--lr", "1e-4", "--resume-step", "500"]}),
    ("run my_app --from-snapshot /mnt/code --experiment-dir /mnt/runs -- python train.py",
     {"from_snapshot": "/mnt/code", "experiment_dir": "/mnt/runs",
      "run_cmd": ["python", "train.py"]}),
    ("run my_app --intent-file intent.md -- python train.py",
     {"intent_file": "intent.md", "run_cmd": ["python", "train.py"]}),
    ("run my_app --store s3://my-experiments/team/ml -- ./t.sh",
     {"store": "s3://my-experiments/team/ml", "run_cmd": ["./t.sh"]}),
    ("run my_app --no-adopt --no-env --no-similar -- python train.py",
     {"capture_env": False, "adopt_run": False, "similar_hint": False,
      "run_cmd": ["python", "train.py"]}),
    ("add my_app --latest --metrics p99_ms=41",
     {"metrics": ["p99_ms=41"], "latest": True}),
    ('add my_app -v @2 --attach checkpoint.pt --note "after warmup"',
     {"version": ["@2"], "note": "after warmup", "attach": "checkpoint.pt"}),
    ("add my_app -v @2 --define-metric val_loss --goal min",
     {"version": ["@2"], "define_metric": "val_loss", "goal": "min"}),
    ('add my_app -v @4 --intent "baseline: plain cross-entropy"',
     {"version": ["@4"], "intent": "baseline: plain cross-entropy"}),
    ('add my_app -v @7 --finish 1 --error OOMKilled --note "closed by orchestrator"',
     {"version": ["@7"], "note": "closed by orchestrator", "finish": 1,
      "finish_error": "OOMKilled"}),
    ("list my_app --archived", {"archived": True}),
    ('list my_app --query "params.batch = 64 and metrics.val_loss < 0.3" --json',
     {"query": "params.batch = 64 and metrics.val_loss < 0.3", "json": True}),
    ("list my_app --sort loss --top 5", {"sort": "loss", "top": 5}),
    ("list my_app --last 10", {"last": 10}),
    ("show my_app --latest", {"latest": True}),
    ("show my_app -v @1 --full-log", {"version": ["@1"], "full_log": True}),
    ("show my_app -v @3 --patch --json --max-bytes 50000",
     {"version": ["@3"], "patch": True, "max_bytes": 50000, "json": True}),
    ("compare my_app --last 3 --json", {"last": 3, "json": True}),
    ("compare my_app -v @1 -v @4 -v @7", {"version": ["@1", "@4", "@7"]}),
    ("diff my_app -v @1 -v @3 --tool delta", {"version": ["@1", "@3"], "tool": "delta"}),
    ("restore my_app -v @2 --force", {"version": ["@2"], "force": True}),
    ("export my_app --latest -o best.tar.gz", {"latest": True, "output": "best.tar.gz"}),
    ("prune my_app --keep 0 --local-only", {"keep": 0, "local_only": True}),
    ("prune my_app --keep 100 --no-trim-journal", {"keep": 100, "no_trim_journal": True}),
    ("prune my_app --older-than 30d --protect-tag stage",
     {"older_than": "30d", "protect_tag": ["stage"]}),
    ("prune my_app --query 'status = \"failed\"' --yes",
     {"query": 'status = "failed"', "yes": True}),
    ("prune my_app -v @4 -v @5 --store s3://bucket/ml",
     {"version": ["@4", "@5"], "store": "s3://bucket/ml"}),
    ("tag my_app @3 stage=prod owner=ann", {"refs": ["@3", "stage=prod", "owner=ann"]}),
    ("tag my_app @3 --remove owner", {"refs": ["@3"], "remove": ["owner"]}),
    ("archive my_app --query 'tags.batch = \"old\"' --dry-run",
     {"dry_run": True, "query": 'tags.batch = "old"'}),
    ("unarchive my_app @2", {"refs": ["@2"]}),
    ("import-mlflow my_app --mlruns ./mlruns --experiment my_exp --experiment 3 --dry-run",
     {"dry_run": True, "mlruns": "./mlruns", "experiment": ["my_exp", "3"]}),
    ("import-mlflow my_app --tracking-uri http://mlflow:5000",
     {"tracking_uri": "http://mlflow:5000"}),
    ("watch my_app --interval 60 --within 6h --compact",
     {"interval": 60.0, "within": "6h", "compact": True}),
    ("lineage my_app -v @8 --depth 2 --json", {"version": ["@8"], "json": True, "depth": 2}),
    ("importance my_app --metric loss --query 'status = \"succeeded\"' --json",
     {"metric": "loss", "query": 'status = "succeeded"', "json": True}),
    ("rewind my_app -v @3 --step 250", {"version": ["@3"], "step": 250}),
    ("rerun my_app -v @3 -- python train.py --lr 0.01",
     {"version": ["@3"], "run_cmd": ["python", "train.py", "--lr", "0.01"]}),
    ("rerun my_app -v @3 --print --json",
     {"version": ["@3"], "print_only": True, "json": True}),
    ("rerun my_app -v @3 --dry-run", {"version": ["@3"], "dry_run": True}),
    ("push my_app -v @3 --adopt", {"version": ["@3"], "adopt": True}),
    ("push my_app --store s3://ml-exps/team --dry-run",
     {"dry_run": True, "store": "s3://ml-exps/team"}),
    ("compact my_app --all-finished", {"all_finished": True}),
    ("compact my_app -v @3 -v @4", {"version": ["@3", "@4"]}),
    ("export-metrics my_app -v @3 --keys loss acc -o metrics.parquet --format parquet",
     {"version": ["@3"], "output": "metrics.parquet", "keys": ["loss", "acc"],
      "metrics_format": "parquet"}),
    ("similar my_app -v @7 --top 5", {"version": ["@7"], "top": 5}),
    ('similar my_app --context "label smoothing" --text-only --all-apps --json',
     {"json": True, "all_apps": True, "context": "label smoothing", "text_only": True}),
    ("similar my_app --context-file intent.md --all-apps --json",
     {"json": True, "all_apps": True, "context_file": "intent.md"}),
    ("similar-backfill my_app --all-apps --dry-run", {"dry_run": True, "all_apps": True}),
    ("backfill-children my_app --dry-run", {"dry_run": True}),
]

DEFAULTS = {
    "debug": False, "command": "experiment", "action": "list", "name": "my_app",
    "refs": [], "run_name": None, "new_app": False, "remove": None, "archived": False,
    "version": None, "note": None, "file": None, "metrics": None, "attach": None,
    "sort": None, "metric": None, "top": None, "last": None, "latest": False,
    "tool": None, "output": None, "keep": None, "older_than": None, "dry_run": False,
    "adopt": False, "print_only": False, "keep_worktree": False, "worktree_dir": None,
    "rerun_cwd": None, "force": False, "local_only": False, "protect_tag": None,
    "no_trim_journal": False, "full_log": False, "patch": False, "max_bytes": 200000,
    "query": None, "yes": False, "json": False, "from_snapshot": None,
    "capture_env": None, "inputs": None, "sync_interval": None,
    "heartbeat_interval": None, "kill_grace_sec": None, "capture_output": True,
    "output_cap_mb": None, "system_metrics": None, "adopt_run": True, "interval": None,
    "within": None, "compact": False, "keys": None, "metrics_format": None,
    "all_finished": False, "all_apps": False, "depth": 1, "parent": None,
    "fork_from": None, "fork_step": None, "step": None, "store": None, "bucket": None,
    "prefix": None, "endpoint_url": None, "experiment_dir": None, "writer_id": None,
    "define_metric": None, "goal": None, "summary": None, "step_metric": None,
    "hidden": None, "chart": None, "finish": None, "force_live": False,
    "finish_error": None, "end_reason": None, "intent": None, "intent_file": None,
    "context": None, "context_file": None, "text_only": False, "similar_hint": None,
    "mlruns": None, "tracking_uri": None, "experiment": None, "skip_artifacts": False,
    "include_deleted": False, "workers": 8, "refresh_features": False, "repo": None,
    "strict_version": False, "run_cmd": None,
}


def _parse(argv):
    register_all()
    return vars(parse_user_commands(["experiment", *argv]))


def test_a_bare_action_parses_to_every_default():
    assert _parse(["list", "my_app"]) == DEFAULTS


@pytest.mark.parametrize("line, changed", CORPUS, ids=[line for line, _ in CORPUS])
def test_each_corpus_line_sets_exactly_its_attributes(line, changed):
    argv = shlex.split(line)
    expected = dict(DEFAULTS, action=argv[0], **changed)
    assert _parse(argv) == expected


@pytest.mark.parametrize("line", [line for line, _ in CORPUS])
def test_no_corpus_line_has_a_foreign_flag(line):
    argv = shlex.split(line)
    register_all()
    args = parse_user_commands(["experiment", *argv])
    assert foreign_flags(args, argv[0], flag_defaults(), ACTION_FLAGS) == []
