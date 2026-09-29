#!/usr/bin/env python3
"""``vmn-exp add <app> -v <ref> --define-metric NAME [--goal] [--summary]
[--step-metric] [--hidden]``: the CLI's ``run.define_metric``.

Appends the same ``define_metric`` log entry the SDK does (see
:mod:`vmn_exp.sdk.metric_defs`), so a finished run — or one recorded by a
plain ``vmn-exp run`` — can still declare how its metrics rank and show.
"""
from vmn_exp.core.metric_schema import hidden_fields
from vmn_exp.core.metric_summary import summary_fields
from vmn_exp.core.step_metric import create_define_metric_entry


def add_define_metric_flags(parser):
    parser.add_argument("--define-metric", dest="define_metric", default=None,
                        metavar="NAME",
                        help="add: declare metric NAME (exact or a glob like 'val_*') "
                             "with --goal/--summary/--step-metric/--hidden")
    parser.add_argument("--goal", default=None, metavar="min|max",
                        help="add --define-metric: which way the metric is better")
    parser.add_argument("--summary", default=None, metavar="POLICY",
                        help="add --define-metric: the value the run ranks on "
                             "(min, max, last, first, mean)")
    parser.add_argument("--step-metric", dest="step_metric", default=None,
                        metavar="METRIC",
                        help="add --define-metric: the metric to chart it against")
    parser.add_argument("--hidden", action="store_true", default=None,
                        help="add --define-metric: keep it out of the ui's default views")


def define_metric_entry(args):
    """The ``define_metric`` entry *args* ask for, None without
    ``--define-metric``; ValueError on a bad policy or no declaration."""
    name = getattr(args, "define_metric", None)
    if name is None:
        return None
    fields = {
        **summary_fields(args.summary, args.goal),
        **hidden_fields(args.hidden),
    }
    if not fields and args.step_metric is None:
        raise ValueError(
            "--define-metric needs --goal, --summary, --step-metric or --hidden"
        )
    return create_define_metric_entry(name, step_metric=args.step_metric, **fields)
