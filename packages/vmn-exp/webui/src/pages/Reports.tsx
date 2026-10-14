import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { apiReports, type ReportRow } from "../apiReports";
import { relTime } from "../util";
import { identityName } from "../util/identity";
import { PageHead, Skeleton } from "../components/ui";
import NewReportDialog from "../components/NewReportDialog";
import ToggleChip from "../components/ToggleChip";

const dash = <span style={{ color: "var(--text-3)" }}>—</span>;

function ReportTableRow({ ws, report }: { ws: string; report: ReportRow }) {
  const updated = report.updated_at ?? report.created_at;
  return (
    <tr>
      <td>
        <Link to={`/ws/${ws}/reports/${encodeURIComponent(report.rid)}`}>{report.title || report.rid}</Link>
        {report.archived && <> <span className="badge">archived</span></>}
      </td>
      <td>{identityName(report.author) ?? identityName(report.created_by) ?? dash}</td>
      <td title={updated ?? ""}>{updated ? relTime(updated) : dash}</td>
      <td>{report.published_rev ? <span className="badge">v{report.published_rev}</span> : dash}</td>
    </tr>
  );
}

function ReportTable({ ws, reports }: { ws: string; reports: ReportRow[] }) {
  if (reports.length === 0) {
    return <div className="card"><div className="empty" style={{ padding: 16 }}>No reports yet.</div></div>;
  }
  return (
    <div className="card">
      <table className="table">
        <thead><tr><th>Title</th><th>Author</th><th>Updated</th><th>Published</th></tr></thead>
        <tbody>{reports.map((r) => <ReportTableRow key={r.rid} ws={ws} report={r} />)}</tbody>
      </table>
    </div>
  );
}

export default function Reports() {
  const { ws = "" } = useParams();
  const [archived, setArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const query = useQuery({
    queryKey: ["reports", ws, archived],
    queryFn: () => apiReports.listReports(ws, archived),
  });
  return (
    <>
      <PageHead title="Reports" mono={false} />
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <ToggleChip pressed={archived} title="include archived reports" onChange={setArchived}>
          archived
        </ToggleChip>
        <button type="button" className="primary" style={{ marginLeft: "auto" }} onClick={() => setCreating(true)}>
          New report
        </button>
      </div>
      {creating && <NewReportDialog ws={ws} onClose={() => setCreating(false)} />}
      {query.error ? <div className="error">{(query.error as Error).message}</div>
        : query.data ? <ReportTable ws={ws} reports={query.data.reports} /> : <Skeleton />}
    </>
  );
}
