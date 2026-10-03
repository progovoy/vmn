/** "Reports using this app/run" (plan 13 §8.2): links, or nothing at all. */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiReports } from "../apiReports";

export default function ReportsUsing({ ws, app, verstr }: { ws: string; app: string; verstr?: string }) {
  const { data } = useQuery({
    queryKey: ["reports-using", ws, app, verstr ?? null],
    queryFn: () => apiReports.reportsUsing(ws, app, verstr),
  });
  const reports = data?.reports ?? [];
  if (!reports.length) return null;
  return (
    <aside className="card reports-using" aria-label="Reports using this">
      <div className="eyebrow">{verstr ? "Reports using this run" : "Reports using this app"}</div>
      <ul>
        {reports.map((r) => (
          <li key={r.rid}>
            <Link to={`/ws/${encodeURIComponent(ws)}/reports/${encodeURIComponent(r.rid)}`}>{r.title || r.rid}</Link>
          </li>
        ))}
      </ul>
    </aside>
  );
}
