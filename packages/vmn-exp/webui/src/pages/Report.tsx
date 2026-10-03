import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { apiReports, commentTarget, type ReportDetail } from "../apiReports";
import { Markdown, type PanelSpec } from "../reports/Markdown";
import Panel from "../reports/Panel";
import ReportHistory from "../reports/ReportHistory";
import { PanelCaptureProvider, usePanelCapture } from "../reports/publishedData";
import Comments from "../components/Comments";
import { Skeleton } from "../components/ui";

/** Which revision to show: ?rev=N, else the draft (live, editors, nothing
 *  published), else the published one (plan 13 decision 1). */
function shownRev(report: ReportDetail, params: URLSearchParams): number {
  const asked = Number(params.get("rev"));
  if (asked > 0) return asked;
  if (params.get("live") === "1" || report.can_edit || !report.published_rev) return report.rev;
  return report.published_rev;
}

function useRevisionBody(ws: string, report: ReportDetail, rev: number) {
  const query = useQuery({
    queryKey: ["report-revision", ws, report.rid, rev],
    queryFn: () => apiReports.getRevision(ws, report.rid, rev),
    enabled: rev !== report.rev,
  });
  return rev === report.rev ? report.body : query.data?.body;
}

function useScrollToHash(ready: boolean) {
  const { hash } = useLocation();
  useEffect(() => {
    if (ready && hash) document.getElementById(hash.slice(1))?.scrollIntoView?.();
  }, [ready, hash]);
}

function PublishedBanner({ report, rev, onLive }: { report: ReportDetail; rev: number; onLive: () => void }) {
  if (!report.published_rev || rev !== report.published_rev || rev === report.rev) return null;
  const date = report.published_at?.slice(0, 10) ?? "";
  return (
    <div className="report-banner">
      published {date} — <button type="button" className="btn btn-sm btn-ghost" onClick={onLive}>view live</button>
    </div>
  );
}

/** The published revision renders frozen panels unless the editor is on it. */
function isFrozen(report: ReportDetail, rev: number, params: URLSearchParams): boolean {
  if (rev !== report.published_rev || params.get("live") === "1") return false;
  return !(report.can_edit && rev === report.rev);
}

function PublishButton({ ws, report }: { ws: string; report: ReportDetail }) {
  const capture = usePanelCapture();
  const client = useQueryClient();
  const publish = useMutation({
    mutationFn: () => apiReports.publish(ws, report.rid, { rev: report.rev, data: capture?.collect() ?? {} }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["report", ws, report.rid] }),
  });
  return (
    <span>
      <button type="button" className="btn btn-sm" disabled={publish.isPending} onClick={() => publish.mutate()}>
        Publish
      </button>
      {publish.error && <span className="error"> {(publish.error as Error).message}</span>}
    </span>
  );
}

function ReportBody({ ws, report }: { ws: string; report: ReportDetail }) {
  const [params, setParams] = useSearchParams();
  const rev = shownRev(report, params);
  const body = useRevisionBody(ws, report, rev);
  useScrollToHash(body !== undefined);
  const target = commentTarget.report(report.rid);
  const published = isFrozen(report, rev, params) ? { rid: report.rid, rev } : undefined;
  const renderPanel = (spec: PanelSpec) => {
    const id = String(spec.id ?? "");
    return (
      <>
        <div id={`p-${id}`}><Panel ws={ws} spec={spec} published={published} /></div>
        {id && <Comments ws={ws} target={target} anchor={{ panel: id }} />}
      </>
    );
  };
  return (
    <PanelCaptureProvider>
      <PublishedBanner report={report} rev={rev} onLive={() => setParams({ live: "1" })} />
      <div className="muted" style={{ marginBottom: 8 }}>
        v{rev}{rev === report.rev ? " (latest)" : ""}{" "}
        {report.can_edit && rev === report.rev && <PublishButton ws={ws} report={report} />}
      </div>
      {body === undefined ? <Skeleton /> : <Markdown source={body} renderPanel={renderPanel} />}
      <ReportHistory ws={ws} rid={report.rid} revisions={report.revisions ?? []}
        defaultBase={report.published_rev ?? Math.max(1, report.rev - 1)} />
      <div className="card">
        <div className="eyebrow">Comments</div>
        <Comments ws={ws} target={target} />
      </div>
    </PanelCaptureProvider>
  );
}

export default function Report() {
  const { ws = "", rid = "" } = useParams();
  const query = useQuery({ queryKey: ["report", ws, rid], queryFn: () => apiReports.getReport(ws, rid) });
  if (query.error) return <div className="error">{(query.error as Error).message}</div>;
  if (!query.data) return <Skeleton />;
  return (
    <>
      <Link className="back-link" to={`/ws/${ws}/reports`}>← reports</Link>
      <div className="page-head"><h1>{query.data.title || rid}</h1></div>
      <ReportBody ws={ws} report={query.data} />
    </>
  );
}
