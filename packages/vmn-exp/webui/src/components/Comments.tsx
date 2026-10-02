import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiReports, type Comment, type CommentAnchor, type NewComment } from "../apiReports";
import { Markdown } from "../reports/Markdown";
import { relTime } from "../util";

interface ThreadProps {
  ws: string;
  target: string;
  /** Only the comments on this panel; without it, the ones on no panel. */
  anchor?: CommentAnchor;
}

const noPanels = () => null;

function TextForm({ label, submit, initial = "", onDone, onCancel }: {
  label: string; submit: string; initial?: string;
  onDone: (text: string) => void; onCancel?: () => void;
}) {
  const [text, setText] = useState(initial);
  const send = () => {
    if (!text.trim()) return;
    onDone(text);
    setText("");
  };
  return (
    <div className="comment-form">
      <textarea aria-label={label} value={text} rows={2} onChange={(e) => setText(e.target.value)} />
      <button type="button" className="btn btn-sm" onClick={send}>{submit}</button>
      {onCancel && <button type="button" className="btn btn-sm btn-ghost" onClick={onCancel}>Cancel</button>}
    </div>
  );
}

type Actions = {
  canEdit: (c: Comment) => boolean;
  add: (body: Omit<NewComment, "target">) => void;
  edit: (id: string, body: { text?: string; resolved?: boolean }) => void;
  remove: (id: string) => void;
  repliesOf: (id: string) => Comment[];
};

function CommentBody({ c, actions }: { c: Comment; actions: Actions }) {
  const [mode, setMode] = useState<"view" | "edit" | "reply">("view");
  if (c.deleted) return <div className="comment-text muted">deleted</div>;
  return (
    <>
      {mode === "edit" ? (
        <TextForm label="Edit comment" submit="Save" initial={c.text ?? ""} onCancel={() => setMode("view")}
          onDone={(text) => { actions.edit(c.id, { text }); setMode("view"); }} />
      ) : (
        <div className="comment-text"><Markdown source={c.text ?? ""} renderPanel={noPanels} /></div>
      )}
      <div className="comment-actions">
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => setMode("reply")}>Reply</button>
        <button type="button" className="btn btn-sm btn-ghost"
          onClick={() => actions.edit(c.id, { resolved: !c.resolved })}>{c.resolved ? "Reopen" : "Resolve"}</button>
        {actions.canEdit(c) && (
          <>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setMode("edit")}>Edit</button>
            <button type="button" className="btn btn-sm btn-ghost"
              onClick={() => window.confirm("Delete this comment?") && actions.remove(c.id)}>Delete</button>
          </>
        )}
      </div>
      {mode === "reply" && (
        <TextForm label="Reply" submit="Send reply" onCancel={() => setMode("view")}
          onDone={(text) => { actions.add({ text, reply_to: c.id }); setMode("view"); }} />
      )}
    </>
  );
}

function CommentItem({ c, actions }: { c: Comment; actions: Actions }) {
  return (
    <div className={`comment${c.resolved ? " resolved" : ""}`} data-testid={`comment-${c.id}`}>
      <div className="comment-meta">
        <strong>{c.author ?? "unknown"}</strong>
        {c.ts && <span className="muted" title={c.ts}> {relTime(c.ts)}</span>}
        {c.resolved && <span className="badge">resolved</span>}
      </div>
      <CommentBody c={c} actions={actions} />
      <div className="comment-replies">
        {actions.repliesOf(c.id).map((r) => <CommentItem key={r.id} c={r} actions={actions} />)}
      </div>
    </div>
  );
}

const inScope = (c: Comment, anchor?: CommentAnchor) =>
  anchor?.panel ? c.anchor?.panel === anchor.panel : !c.anchor?.panel;

function useThreadActions(ws: string, target: string, anchor: CommentAnchor | undefined,
  comments: Comment[], me: string | null | undefined): Actions {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ["comments", ws, target] });
  const add = useMutation({ mutationFn: (b: NewComment) => apiReports.addComment(ws, b), onSuccess: refresh });
  const edit = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { text?: string; resolved?: boolean } }) =>
      apiReports.editComment(ws, target, id, body),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: (id: string) => apiReports.deleteComment(ws, target, id), onSuccess: refresh });
  return {
    canEdit: (c) => !me || c.author === me,
    add: (body) => add.mutate({ target, ...body, ...(anchor && !body.reply_to ? { anchor } : {}) }),
    edit: (id, body) => edit.mutate({ id, body }),
    remove: (id) => remove.mutate(id),
    repliesOf: (id) => comments.filter((c) => c.reply_to === id),
  };
}

export default function Comments({ ws, target, anchor }: ThreadProps) {
  const query = useQuery({
    queryKey: ["comments", ws, target],
    queryFn: () => apiReports.listComments(ws, target),
  });
  const comments = query.data?.comments ?? [];
  const actions = useThreadActions(ws, target, anchor, comments, query.data?.me);
  const ids = new Set(comments.map((c) => c.id));
  const roots = comments.filter((c) => !(c.reply_to && ids.has(c.reply_to)) && inScope(c, anchor));
  return (
    <div className="comments">
      {query.error && <div className="error">{(query.error as Error).message}</div>}
      {roots.map((c) => <CommentItem key={c.id} c={c} actions={actions} />)}
      <TextForm label="New comment" submit="Comment" onDone={(text) => actions.add({ text })} />
    </div>
  );
}
