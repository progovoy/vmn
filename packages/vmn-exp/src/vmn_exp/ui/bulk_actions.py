"""Bulk run actions by query (plan 23 S4).

``exp_archive``/``exp_unarchive``/``exp_tag`` take ``{scope, q, status,
archived}`` instead of ``{verstrs}``/``{verstr}``: the runs the leaderboard
list shows for the same filters. Only the runs the action would change are
counted and acted on (an archived run is not archived again, a run already
carrying the tags is not tagged again), so a bulk action is idempotent.
:class:`BulkSpec` resolves them, previews them (``dry_run``) and acts on a
batch, in a store (in-process) or a checkout (``vmn-exp`` argv).
"""
from vmn_exp.core.manage import set_archived, tag_run
from vmn_exp.ui.jobs_exp_meta import _tag_args

BULK_ACTIONS = ("exp_archive", "exp_unarchive", "exp_tag")
QUERY_KEYS = ("scope", "q", "status")
SAMPLE_SIZE = 10


def is_bulk(action, body):
    """True when *body* asks *action* for the runs of a query."""
    return (action in BULK_ACTIONS and isinstance(body, dict)
            and "verstrs" not in body and "verstr" not in body
            and any(k in body for k in QUERY_KEYS))


class BulkSpec:
    def __init__(self, action, app_name, body, tag_args=None):
        self.action, self.app_name, self.body = action, app_name, body
        self.verb = action.split("_", 1)[1]
        self.tag_args = tag_args

    @classmethod
    def build(cls, action, app_name, body):
        """``(BulkSpec, None)`` or ``(None, error)``."""
        if action != "exp_tag":
            return cls(action, app_name, body), None
        args, err = _tag_args(body.get("set") or {}, body.get("remove") or [])
        return (None, err) if err else (cls(action, app_name, body, args), None)

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

    def commands(self, batch):
        """The ``vmn-exp`` argv acting on *batch* in a checkout."""
        head = ["vmn-exp", "experiment", self.verb, self.app_name]
        if self.action == "exp_tag":
            return [head + [v] + self.tag_args for v in batch]
        return [head + list(batch)]

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
        for verstr in batch:
            if self.action == "exp_tag":
                done = tag_run(storage, self.app_name, verstr,
                               self.body.get("set") or {}, self.body.get("remove") or [])
            else:
                done = set_archived(storage, self.app_name, verstr, self.action == "exp_archive")
            if not done:
                raise RuntimeError(f"Experiment '{verstr}' not found for {self.app_name}")
            hint(self.app_name, verstr)
        return "\n".join(batch)
