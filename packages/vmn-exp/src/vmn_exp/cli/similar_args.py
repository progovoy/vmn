"""The ``vmn-exp similar`` flags (``--context``/``--context-file``,
``--text-only``) and the submission hint's opt-out (``--no-similar`` on
``create``/``run``), with the reading of a context.

A context file is read like an ``--intent-file``: optional YAML front matter
whose ``keywords`` join the query text (its other keys do not), ``-`` for
stdin — so the agent's ``intent.md`` doubles as the query.
"""
from version_stamp.api import VMN_LOGGER
from vmn_exp.cli.intent_arg import read_file_arg
from vmn_exp.core.intent import parse_intent_file


def add_similar_flags(parser):
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--context", default=None, metavar="TEXT",
                       help="similar: a text query, combined with the target's code facts "
                            "(the working tree, or the -v run); it replaces the target's text")
    group.add_argument("--context-file", dest="context_file", default=None, metavar="PATH|-",
                       help="similar: like --context, read from a file ('-': stdin) that "
                            "may start with YAML front matter (its keywords join the query)")
    parser.add_argument("--text-only", dest="text_only", action="store_true", default=False,
                        help="similar: match the --context text alone (no code, params, "
                             "inputs or other facts; needs no working tree)")
    parser.add_argument("--no-similar", dest="similar_hint", action="store_false", default=None,
                        help="create/run: don't print the similar past runs after the claim "
                             "(also: conf experiment.similar.hint: false)")


def read_context(args):
    """``(text, None)`` for the context *args* give — text None without the
    flags or for a blank one — or ``(None, 1)`` after logging why it is unusable."""
    path = getattr(args, "context_file", None)
    try:
        text = _from_file(path) if path is not None else getattr(args, "context", None)
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return None, 1
    return (text if text and text.strip() else None), None


def _from_file(path):
    text, keywords, _generator = parse_intent_file(read_file_arg(path, "--context-file"))
    return "\n".join([text] + list(keywords or ()))
