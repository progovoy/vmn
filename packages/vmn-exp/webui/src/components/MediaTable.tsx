import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { get } from "../http";
import type { TableItem, TablePage } from "../types";
import { tablePageUrl } from "../util/media";

export const TABLE_PAGE_ROWS = 50;

type Sort = { column: string; order: "asc" | "desc" } | null;

function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function nextSort(sort: Sort, column: string): Sort {
  if (sort?.column !== column) return { column, order: "asc" };
  return sort.order === "asc" ? { column, order: "desc" } : null;
}

function Pager({ offset, total, onPage }: {
  offset: number; total: number; onPage: (offset: number) => void;
}) {
  const last = Math.min(offset + TABLE_PAGE_ROWS, total);
  return (
    <div className="media-pager">
      <button className="link" disabled={offset === 0}
        onClick={() => onPage(Math.max(offset - TABLE_PAGE_ROWS, 0))}>← prev</button>
      <span className="muted">{total ? offset + 1 : 0}–{last} of {total}</span>
      <button className="link" disabled={last >= total}
        onClick={() => onPage(offset + TABLE_PAGE_ROWS)}>next →</button>
    </div>
  );
}

function TableView({ ws, app, verstr, item }: {
  ws: string; app: string; verstr: string; item: TableItem;
}) {
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<Sort>(null);
  const url = tablePageUrl(ws, app, verstr, item.path, {
    offset, limit: TABLE_PAGE_ROWS, sort: sort?.column, order: sort?.order,
  });
  // A logged table never changes: fetched once per page and order.
  const query = useQuery({
    queryKey: ["table", url], queryFn: () => get<TablePage>(url),
    staleTime: Infinity, placeholderData: keepPreviousData,
  });
  if (query.error) return <div className="error">{String(query.error)}</div>;
  const page = query.data;
  if (!page) return <div className="artifact-loading">loading table…</div>;
  const arrow = (name: string) =>
    sort?.column === name ? (sort.order === "asc" ? " ▲" : " ▼") : "";
  return (
    <>
      <div className="artifact-table">
        <table>
          <thead>
            <tr>
              {page.columns.map((c) => (
                <th key={c.name} title={c.type}>
                  <button className="link" onClick={() => { setSort(nextSort(sort, c.name)); setOffset(0); }}>
                    {c.name}{arrow(c.name)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {page.rows.map((row, i) => (
              <tr key={offset + i}>{row.map((v, j) => <td key={j}>{cellText(v)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager offset={offset} total={page.total} onPage={setOffset} />
      {page.truncated && item.total_rows != null && (
        <div className="artifact-note">logged {item.total_rows} rows; the first {page.total} were kept</div>
      )}
    </>
  );
}

/** A logged table viewer: pick a key and step, page and sort server-side. */
export default function MediaTable({ ws, app, verstr, tables }: {
  ws: string; app: string; verstr: string; tables: Record<string, TableItem[]>;
}) {
  const keys = Object.keys(tables).filter((k) => tables[k].length > 0);
  const [key, setKey] = useState(keys[0]);
  const [picked, setPicked] = useState<number | null>(null);
  const items = tables[key] ?? tables[keys[0]] ?? [];
  if (items.length === 0) return null;
  const index = Math.min(picked ?? items.length - 1, items.length - 1);
  const item = items[index];
  return (
    <div className="media-table">
      <div className="media-tile-head">
        {keys.length > 1 ? (
          <select aria-label="table" value={key} onChange={(e) => { setKey(e.target.value); setPicked(null); }}>
            {keys.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        ) : <span className="mono">{keys[0]}</span>}
        {items.length > 1 ? (
          <select aria-label="table step" value={index} onChange={(e) => setPicked(Number(e.target.value))}>
            {items.map((it, i) => <option key={it.step} value={i}>step {it.step}</option>)}
          </select>
        ) : <span className="muted">step {item.step}</span>}
      </div>
      <TableView key={item.path} ws={ws} app={app} verstr={verstr} item={item} />
    </div>
  );
}
