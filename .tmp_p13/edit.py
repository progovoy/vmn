import os
os.chdir("/Users/pavelr/projects/vmn/.claude/worktrees/wf_d6897350-c89-7/packages/vmn-exp/webui/src/reports")


def edit(p, pairs):
    s = open(p).read()
    for a, b in pairs:
        assert a in s, (p, a)
        s = s.replace(a, b)
    open(p, "w").write(s)


edit("publishedData.tsx", [
    ('import { createContext, useContext, useMemo, useState,', 'import { createContext, useContext, useEffect, useMemo, useState,'),
    ("  useState(() => (capture && id ? capture.register(id, app, client) : null));",
     "  useEffect(() => (capture && id ? capture.register(id, app, client) : undefined), [capture, id, app, client]);"),
])
edit("Panel.tsx", [
    ('import type { ReactNode } from "react";', 'import { useMemo, type ReactNode } from "react";\nimport { QueryClientProvider, useQuery } from "@tanstack/react-query";\nimport { apiReports } from "../apiReports";'),
    ('import { useQueryVerstrs } from "./panelData";', 'import { useQueryVerstrs } from "./panelData";\nimport { frozenClient, LivePanelScope, type PanelPayload } from "./publishedData";'),
    ('''export default function Panel({ ws, spec }: { ws: string; spec: unknown }) {
  const result''', '''/** Where a published revision keeps its panels' data. */
export type PublishedRef = { rid: string; rev: number };

function PublishedBody({ ws, spec, published }: { ws: string; spec: PanelSpec; published: PublishedRef }) {
  const id = String(spec.id ?? "");
  const q = useQuery({
    queryKey: ["report-panel-data", ws, published.rid, published.rev, id],
    queryFn: () => apiReports.getPanelData(ws, published.rid, published.rev, id),
    staleTime: Infinity,
  });
  const client = useMemo(() => (q.data ? frozenClient(q.data as PanelPayload) : null), [q.data]);
  if (q.error) return <div className="muted">No published data for this panel</div>;
  if (!client) return <div className="muted">Loading…</div>;
  return <QueryClientProvider client={client}>{body(ws, spec)}</QueryClientProvider>;
}

function LiveBody({ ws, spec }: { ws: string; spec: PanelSpec }) {
  return <LivePanelScope id={String(spec.id ?? "")} app={spec.app}>{body(ws, spec)}</LivePanelScope>;
}

export default function Panel({ ws, spec, published }: { ws: string; spec: unknown; published?: PublishedRef }) {
  const result'''),
    ('<LazyMount height={s.height ?? DEFAULT_HEIGHT}>{body(ws, s)}</LazyMount>', '''<LazyMount height={s.height ?? DEFAULT_HEIGHT}>
        {published ? <PublishedBody ws={ws} spec={s} published={published} /> : <LiveBody ws={ws} spec={s} />}
      </LazyMount>'''),
])
edit("RunPanels.tsx", [
    ('''  const q = useRunDetail(ws, app, verstr);
  if (q.error) return''', '''  const q = useRunDetail(ws, app, verstr);
  if ((q.error as HttpError | null)?.status === 404) return <div className="muted">run pruned: {verstr}</div>;
  if (q.error) return'''),
    ('import { runLineage } from "../apiRun";', 'import { runLineage } from "../apiRun";\nimport type { HttpError } from "../http";'),
])
