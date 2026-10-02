import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiReports, type RevisionMeta } from "../apiReports";
import { relTime } from "../util";
import { lineDiff } from "./lineDiff";

const SIGN = { same: " ", add: "+", del: "-" } as const;

function RevisionDiff({ ws, rid, a, b }: { ws: string; rid: string; a: number; b: number }) {
  const rev = (n: number) => ({
    queryKey: ["report-revision", ws, rid, n],
    queryFn: () => apiReports.getRevision(ws, rid, n),
  });
  const left = useQuery(rev(a));
  const right = useQuery(rev(b));
  if (!left.data || !right.data) return null;
  return (
    <pre className="report-diff" aria-label={`diff v${a} v${b}`}>
      {lineDiff(left.data.body, right.data.body).map((l, i) => (
        <div key={i} className={`diff-${l.op}`}>{`${SIGN[l.op]} ${l.text}`}</div>
      ))}
    </pre>
  );
}

function RevSelect({ label, value, revisions, onChange }: {
  label: string; value: number; revisions: RevisionMeta[]; onChange: (n: number) => void;
}) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(Number(e.target.value))}>
      {revisions.map((r) => <option key={r.rev} value={r.rev}>v{r.rev}</option>)}
    </select>
  );
}

export default function ReportHistory({ ws, rid, revisions, defaultBase }: {
  ws: string; rid: string; revisions: RevisionMeta[]; defaultBase: number;
}) {
  const latest = revisions.length ? revisions[revisions.length - 1].rev : 0;
  const [a, setA] = useState(defaultBase);
  const [b, setB] = useState(latest);
  const [diff, setDiff] = useState<[number, number] | null>(null);
  const base = `/ws/${ws}/reports/${encodeURIComponent(rid)}`;
  return (
    <div className="card report-history">
      <div className="eyebrow">Revisions</div>
      <ul>
        {revisions.map((r) => (
          <li key={r.rev}>
            <Link to={`${base}?rev=${r.rev}`}>v{r.rev}</Link>{" "}
            {r.author && <span>{r.author}</span>}{" "}
            {r.created_at && <span className="muted" title={r.created_at}>{relTime(r.created_at)}</span>}{" "}
            {r.message && <span>{r.message}</span>}
          </li>
        ))}
      </ul>
      {revisions.length > 1 && (
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <RevSelect label="From revision" value={a} revisions={revisions} onChange={setA} />
          <RevSelect label="To revision" value={b} revisions={revisions} onChange={setB} />
          <button type="button" className="btn btn-sm" onClick={() => setDiff([a, b])}>Compare</button>
        </div>
      )}
      {diff && <RevisionDiff ws={ws} rid={rid} a={diff[0]} b={diff[1]} />}
    </div>
  );
}
