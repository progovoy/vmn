import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiReports, type ReportRow } from "../apiReports";
import { relTime } from "../util";
import { PageHead, Skeleton } from "../components/ui";

const dash = <span style={{ color: "var(--text-3)" }}>—</span>;

function ReportTableRow({ ws, report }: { ws: string; report: ReportRow }) {
  const updated = report.updated_at ?? report.created_at;
  return (
    <tr>
      <td>
        <Link to={`/ws/${ws}/reports/${encodeURIComponent(report.rid)}`}>{report.title || report.rid}</Link>
        {report.archived && <> <span className="badge">archived</span></>}
      </td>
      <td>{report.author ?? report.created_by ?? dash}</td>
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

function NewReport({ ws }: { ws: string }) {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    try {
      const { rid } = await apiReports.createReport(ws, { title: title.trim() || "Untitled report", body: "" });
      navigate(`/ws/${ws}/reports/${encodeURIComponent(rid)}/edit`);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <span style={{ display: "inline-flex", gap: 6, marginLeft: 16 }}>
      <input aria-label="New report title" placeholder="title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <button type="button" className="btn" onClick={() => void create()}>New report</button>
      {error && <span role="alert" className="error">{error}</span>}
    </span>
  );
}

export default function Reports() {
  const { ws = "" } = useParams();
  const [archived, setArchived] = useState(false);
  const query = useQuery({
    queryKey: ["reports", ws, archived],
    queryFn: () => apiReports.listReports(ws, archived),
  });
  return (
    <>
      <PageHead title="Reports" what={ws} mono={false} />
      <label style={{ display: "inline-flex", gap: 6, marginBottom: 12 }}>
        <input type="checkbox" aria-label="Show archived" checked={archived}
          onChange={(e) => setArchived(e.target.checked)} />
        show archived
      </label>
      <NewReport ws={ws} />
      {query.error ? <div className="error">{(query.error as Error).message}</div>
        : query.data ? <ReportTable ws={ws} reports={query.data.reports} /> : <Skeleton />}
    </>
  );
}
