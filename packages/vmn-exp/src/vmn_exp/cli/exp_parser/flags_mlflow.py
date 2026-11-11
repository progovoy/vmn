"""``import-mlflow``'s flags."""


def add_mlflow(parser):
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--mlruns", default=None, metavar="DIR",
                        help="import-mlflow: path to mlruns/ FileStore directory")
    source.add_argument("--tracking-uri", default=None, metavar="URI",
                        help="import-mlflow: MLflow tracking server URI "
                             "(requires mlflow-skinny)")
    parser.add_argument("--experiment", action="append", default=None,
                        metavar="NAME_OR_ID",
                        help="import-mlflow: include only this experiment (repeatable)")
    parser.add_argument("--skip-artifacts", action="store_true", default=False,
                        help="import-mlflow: do not copy local artifacts")
    parser.add_argument("--include-deleted", action="store_true", default=False,
                        help="import-mlflow: include deleted/trashed runs")
    parser.add_argument("--workers", type=int, default=8,
                        help="import-mlflow: parallel import workers (default: 8)")
    parser.add_argument("--refresh-features", action="store_true", default=False,
                        help="import-mlflow: give already-imported runs the features "
                             "(author, entrypoint, branch) and note they lack")
    parser.add_argument("--repo", default=None, metavar="PATH",
                        help="import-mlflow: a checkout holding the runs' source commits, "
                             "to record what each commit's branch changed")
