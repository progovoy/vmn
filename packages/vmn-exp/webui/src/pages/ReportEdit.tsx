import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { apiReports } from "../apiReports";
import { PageHead, Skeleton } from "../components/ui";
import { Markdown, type PanelSpec } from "../reports/Markdown";
import Panel from "../reports/Panel";
import PanelDialog from "../reports/PanelDialog";
import { insertPanelBlock, replacePanelBlock } from "../reports/panelBlocks";
import ConflictResolve from "../reports/ConflictResolve";
import { merge3, type MergeChunk } from "../reports/merge";
import type { HttpError } from "../http";
import { clearDraft, draftKey, loadDraft, useDraftAutosave } from "../reports/useReportDraft";

export { DRAFT_SAVE_MS } from "../reports/useReportDraft";

type Dialog = { mode: "insert"; at: number } | { mode: "edit"; raw: string; spec: PanelSpec };
interface Editing { body: string; base: number; saved: string }
interface Theirs { rev: number; body: string; author?: string | null }
interface Conflict { chunks: MergeChunk[]; theirs: Theirs }

function useEditing(ws: string, rid: string) {
  const query = useQuery({ queryKey: ["report", ws, rid], queryFn: () => apiReports.getReport(ws, rid) });
  const [editing, setEditing] = useState<Editing | null>(null);
  const key = draftKey(ws, rid);
  useEffect(() => {
    if (!query.data || editing) return;
    const draft = loadDraft(key);
    setEditing({ body: draft?.body ?? query.data.body, base: draft?.base ?? query.data.rev, saved: query.data.body });
  }, [query.data, editing, key]);
  const dirty = editing && editing.body !== editing.saved ? editing : null;
  useDraftAutosave(key, dirty);
  return { query, editing, setEditing, key };
}

export default function ReportEdit() {
  const { ws = "", rid = "" } = useParams();
  const client = useQueryClient();
  const { query, editing, setEditing, key } = useEditing(ws, rid);
  const [message, setMessage] = useState("");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  const setBody = (body: string) => setEditing((e) => (e ? { ...e, body } : e));

  const [conflict, setConflict] = useState<Conflict | null>(null);

  const write = useCallback(async (body: string, base: number, note: string) => {
    const { rev } = await apiReports.saveRevision(ws, rid, { base, body, ...(message ? { message } : {}) });
    clearDraft(key);
    setEditing((e) => (e ? { ...e, body, base: rev, saved: body } : e));
    setMessage("");
    setStatus(`${note}saved revision ${rev}`);
    client.invalidateQueries({ queryKey: ["report", ws, rid] });
  }, [message, ws, rid, key, setEditing, client]);

  const onConflict = useCallback(async (theirs: Theirs, base: number, yours: string) => {
    const { body: baseBody } = await apiReports.getRevision(ws, rid, base);
    const merged = merge3(baseBody, theirs.body, yours);
    if (merged.text !== undefined) return write(merged.text, theirs.rev, `merged with revision ${theirs.rev}; `);
    setEditing((e) => (e ? { ...e, base: theirs.rev } : e));
    setConflict({ chunks: merged.chunks, theirs });
  }, [ws, rid, write, setEditing]);

  const attempt = useCallback(async (body: string, base: number) => {
    try {
      await write(body, base, "");
    } catch (err) {
      const e = err as HttpError;
      try {
        if (e.status === 409) await onConflict(e.body as Theirs, base, body);
        else setStatus(e.message);
      } catch (inner) {
        setStatus((inner as Error).message);
      }
    }
  }, [write, onConflict]);

  const save = useCallback(async () => {
    if (editing) await attempt(editing.body, editing.base);
  }, [editing, attempt]);

  const saveResolved = (body: string) => {
    if (!conflict) return;
    setConflict(null);
    void attempt(body, conflict.theirs.rev);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      void save();
    }
  };

  const renderPanel = useCallback((spec: PanelSpec, raw: string) => (
    <div className="report-edit-panel">
      <button type="button" className="btn" aria-label={`Edit panel ${String(spec.id ?? "")}`}
        onClick={() => setDialog({ mode: "edit", raw, spec })}>⚙</button>
      <Panel ws={ws} spec={spec} />
    </div>
  ), [ws]);

  const submitDialog = (spec: PanelSpec) => {
    if (!editing || !dialog) return;
    setBody(dialog.mode === "insert"
      ? insertPanelBlock(editing.body, dialog.at, spec)
      : replacePanelBlock(editing.body, dialog.raw, spec));
    setDialog(null);
  };

  if (query.error) return <div className="error">{(query.error as Error).message}</div>;
  if (!editing) return <Skeleton />;
  return (
    <div onKeyDown={onKeyDown}>
      <Link className="back-link" to={`/ws/${ws}/reports/${encodeURIComponent(rid)}`}>← report</Link>
      <PageHead title={query.data?.title || rid} what="editing" mono={false} />
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <button type="button" className="btn"
          onClick={() => setDialog({ mode: "insert", at: textarea.current?.selectionStart ?? editing.body.length })}>
          Insert panel
        </button>
        <input aria-label="Revision message" placeholder="message (optional)" value={message}
          onChange={(e) => setMessage(e.target.value)} />
        <button type="button" className="btn" onClick={() => void save()}>Save</button>
        {status && <span role="status">{status}</span>}
      </div>
      {conflict && (
        <ConflictResolve chunks={conflict.chunks} theirsAuthor={conflict.theirs.author}
          onSave={saveResolved} onCancel={() => setConflict(null)} />
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <textarea ref={textarea} aria-label="Report source" className="mono" style={{ minHeight: "70vh" }}
          value={editing.body} onChange={(e) => setBody(e.target.value)} />
        <div className="card"><Markdown source={editing.body} renderPanel={renderPanel} /></div>
      </div>
      {dialog && (
        <PanelDialog initial={dialog.mode === "edit" ? dialog.spec : undefined}
          onSubmit={submitDialog} onClose={() => setDialog(null)} />
      )}
    </div>
  );
}
