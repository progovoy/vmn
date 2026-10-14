"""Bulk run actions by query (plan 23 S4).

``exp_archive``/``exp_unarchive``/``exp_tag`` take ``{scope, q, status,
archived}`` instead of ``{verstrs}``/``{verstr}``: the runs the leaderboard
list shows for the same filters. Only the runs the action would change are
counted and acted on (an archived run is not archived again, a run already
carrying the tags is not tagged again), so a bulk action is idempotent.
:class:`BulkSpec` resolves them, previews them (``dry_run``) and acts on a
batch, in a store (in-process) or a checkout (``vmn-exp`` argv).
"""
from vmn_exp.ui.jobs_exp_meta import _tag_args, exp_archive_command, exp_tag_command
from vmn_exp.ui.jobs_store import build_store_action

BULK_ACTIONS = ("exp_archive", "exp_unarchive", "exp_tag")
QUERY_KEYS = ("scope", "q", "status")
SAMPLE_SIZE = 10


def is_bulk(action, body):
    """True when *body* asks *action* for the runs of a query."""
    return (action in BULK_ACTIONS and isinstance(body, dict)
            and "verstrs" not in body and "verstr" not in body
            and any(k in body for k in QUERY_KEYS))


class BulkSpec:
    def __init__(self, action, app_name, body):
        self.action, self.app_name, self.body = action, app_name, body
        self.verb = action.split("_", 1)[1]

    @classmethod
    def build(cls, action, app_name, body):
        """``(BulkSpec, None)`` or ``(None, error)``."""
        if action == "exp_tag":
            _, err = _tag_args(body.get("set") or {}, body.get("remove") or [])
            if err:
                return None, err
        return cls(action, app_name, body), None

    @property
    def label(self):
        """The job's command: the action and its filters."""
        return [self.action, self.app_name] + [
            f"{k}={self.body[k]}" for k in QUERY_KEYS if self.body.get(k)]

    def filters(self):
        """The list's filters; archive/unarchive see every run and pick by state."""
        archived = self.action != "exp_tag" or bool(self.body.get("archived"))
        return dict(scope=self.body.get("scope"), query=self.body.get("q"),
                    status=self.body.get("status"), archived=archived)

    def pending(self, row):
        """True when acting on *row* would change it."""
        if self.action == "exp_archive":
            return not row.get("archived")
        if self.action == "exp_unarchive":
            return bool(row.get("archived"))
        tags = row.get("tags") or {}
        to_set, to_remove = self.body.get("set") or {}, self.body.get("remove") or []
        return any(tags.get(k) != v for k, v in to_set.items()) or any(k in tags for k in to_remove)

    def matching(self, rows):
        return [row["verstr"] for row in rows if self.pending(row)]

    @staticmethod
    def preview(verstrs):
        return {"count": len(verstrs), "sample": verstrs[:SAMPLE_SIZE]}

    def _bodies(self, batch):
        """The single-run action bodies acting on *batch*: one per run for a
        tag, one for an archive/unarchive batch."""
        if self.action == "exp_tag":
            edit = {k: self.body[k] for k in ("set", "remove") if k in self.body}
            return [dict(edit, verstr=v) for v in batch]
        return [{"verstrs": list(batch)}]

    def commands(self, batch):
        """The ``vmn-exp`` argv acting on *batch* in a checkout."""
        if self.action == "exp_tag":
            built = [exp_tag_command(self.app_name, body) for body in self._bodies(batch)]
        else:
            built = [exp_archive_command(self.verb, self.app_name, body)
                     for body in self._bodies(batch)]
        return [_built(command, err) for command, err in built]

    def run_in_checkout(self, run_command, cwd, batch):
        """Act on *batch* through ``vmn-exp`` in *cwd*; the log text."""
        logs = []
        for command in self.commands(batch):
            code, output = run_command(command, cwd)
            if code:
                raise RuntimeError(output)
            logs.append(output)
        return "".join(logs)

    def apply(self, storage, batch, hint):
        """Act on *batch* in a store; the log text."""
        actions = [build_store_action(self.action, self.app_name, body)
                   for body in self._bodies(batch)]
        return "\n".join(_built(action, err).run(storage, hint) for action, err in actions)


def _built(value, err):
    """What a single-run builder built; its error raised."""
    if err:
        raise RuntimeError(err)
    return value
