/** Report panels about one run: media, table, histogram, lineage, run card. */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { appTag } from "../api";
import { runLineage } from "../apiRun";
import type { HttpError } from "../http";
import type { ExperimentDetail } from "../types";
import { fmtParam, fmtVal } from "../util";
import MediaImages from "../components/MediaImages";
import MediaTable from "../components/MediaTable";
import RunHistograms from "../components/RunHistograms";
import { LineageView } from "../components/RunLineage";
import StatusPill from "../components/StatusPill";
import type { PanelSpec } from "./panelSpec";
import { useRunDetail } from "./panelData";
import { useMediaUrl, type MediaUrl } from "./mediaUrl";

export type RunSpec = Extract<PanelSpec, { type: "media" | "table" | "histogram" | "lineage" | "run" }>;
export const RUN_TYPES = new Set(["media", "table", "histogram", "lineage", "run"]);

const CARD_METRICS = 8;

function WithDetail({ ws, app, verstr, children }: {
  ws: string; app: string; verstr: string; children: (d: ExperimentDetail) => ReactNode;
}) {
  const q = useRunDetail(ws, app, verstr);
  if ((q.error as HttpError | null)?.status === 404) return <div className="muted">run pruned: {verstr}</div>;
  if (q.error) return <div className="error">{String(q.error)}</div>;
  return q.data ? <>{children(q.data)}</> : <div className="muted">Loading…</div>;
}

function Lineage({ ws, app, verstr, depth }: { ws: string; app: string; verstr: string; depth: number }) {
  const q = useQuery({
    queryKey: ["lineage", ws, app, verstr, depth],
    queryFn: () => runLineage(ws, app, verstr, depth),
  });
  if (q.error) return <div className="error">{String(q.error)}</div>;
  return q.data ? <LineageView ws={ws} lineage={q.data} /> : <div className="muted">Loading lineage…</div>;
}

function RunCard({ ws, app, detail }: { ws: string; app: string; detail: ExperimentDetail }) {
  const verstr = detail.metadata.verstr;
  const metrics = Object.entries(detail.metrics).slice(0, CARD_METRICS);
  const params = Object.entries(detail.params ?? {});
  return (
    <div className="panel-run-card">
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Link className="mono" to={`/ws/${ws}/app/${appTag(app)}/run/${encodeURIComponent(verstr)}`}>{verstr}</Link>
        {detail.status && (
          <StatusPill status={detail.status.status} exitCode={detail.status.exit_code}
            durationSec={detail.status.duration_sec} staleSec={detail.status.stale_sec} />
        )}
      </div>
      <dl className="kv">
        {metrics.map(([k, v]) => [<dt key={`m.${k}`}>{k}</dt>, <dd key={`mv.${k}`} className="mono">{fmtVal(v)}</dd>])}
        {params.map(([k, v]) => [<dt key={`p.${k}`}>{k}</dt>, <dd key={`pv.${k}`} className="mono">{fmtParam(v)}</dd>])}
      </dl>
    </div>
  );
}

function render(ws: string, spec: RunSpec, d: ExperimentDetail, mediaUrl: MediaUrl): ReactNode {
  const { app } = spec;
  const verstr = d.metadata.verstr;
  switch (spec.type) {
    case "media": {
      const items = d.media?.[spec.key] ?? [];
      const step = spec.step ?? "last";
      const shown = step === "last" ? items : items.filter((i) => i.step === step);
      return <MediaImages media={{ [spec.key]: shown }} url={(p) => mediaUrl(ws, app, verstr, p)} />;
    }
    case "table": {
      const entry = Object.entries(d.tables ?? {}).find(([, items]) => items.some((i) => i.path === spec.path));
      if (!entry) return <div className="muted">No table at {spec.path}</div>;
      const [key, items] = entry;
      return <MediaTable ws={ws} app={app} verstr={verstr} tables={{ [key]: items.filter((i) => i.path === spec.path) }} />;
    }
    case "histogram": {
      const inline = d.histograms?.[spec.key];
      return (
        <RunHistograms ws={ws} app={app} verstr={verstr} totals={{ [spec.key]: d.histograms_total?.[spec.key] ?? 0 }}
          inline={inline ? { [spec.key]: inline } : undefined} />
      );
    }
    case "run":
      return <RunCard ws={ws} app={app} detail={d} />;
    case "lineage":
      return null;
  }
}

export function RunPanel({ ws, spec }: { ws: string; spec: RunSpec }) {
  const mediaUrl = useMediaUrl();
  const verstr = spec.runs.verstrs[0];
  if (spec.type === "lineage") return <Lineage ws={ws} app={spec.app} verstr={verstr} depth={spec.depth ?? 1} />;
  return <WithDetail ws={ws} app={spec.app} verstr={verstr}>{(d) => render(ws, spec, d, mediaUrl)}</WithDetail>;
}
