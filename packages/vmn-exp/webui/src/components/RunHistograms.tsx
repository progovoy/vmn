import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { get } from "../http";
import type { HistogramItem, HistogramPage } from "../types";
import { histogramUrl } from "../util/media";
import { HistogramKey } from "./MediaHistograms";

/** Keys fetched and drawn before "show more": a watched model has hundreds. */
export const HISTOGRAM_KEYS_SHOWN = 12;

function FetchedHistogram({ ws, app, verstr, name, total, inline }: {
  ws: string; app: string; verstr: string; name: string; total: number;
  inline?: HistogramItem[];
}) {
  const url = histogramUrl(ws, app, verstr, name);
  // Refetched only when the key gains steps (the detail's poll moves `total`).
  const query = useQuery({
    queryKey: ["histogram", url, total], queryFn: () => get<HistogramPage>(url),
    staleTime: Infinity, placeholderData: keepPreviousData,
    // A small run's detail inlines the steps: nothing to fetch.
    initialData: inline && { name, steps: inline, total },
  });
  if (query.error) return <div className="error">{String(query.error)}</div>;
  const page = query.data;
  if (!page) return <div className="media-tile artifact-loading">loading {name}…</div>;
  if (page.steps.length === 0) return null;
  return <HistogramKey name={name} items={page.steps} total={page.total} />;
}

/** A run's histograms, each key's steps fetched on its own unless the
 *  detail inlined them. */
export default function RunHistograms({ ws, app, verstr, totals, inline }: {
  ws: string; app: string; verstr: string; totals: Record<string, number>;
  inline?: Record<string, HistogramItem[]>;
}) {
  const [shown, setShown] = useState(HISTOGRAM_KEYS_SHOWN);
  const names = Object.keys(totals);
  if (names.length === 0) return null;
  const hidden = names.length - shown;
  return (
    <>
      <div className="media-grid">
        {names.slice(0, shown).map((name) => (
          <FetchedHistogram key={name} ws={ws} app={app} verstr={verstr} name={name}
            total={totals[name]} inline={inline?.[name]} />
        ))}
      </div>
      {hidden > 0 && (
        <button className="link" onClick={() => setShown((n) => n + HISTOGRAM_KEYS_SHOWN)}>
          show {Math.min(hidden, HISTOGRAM_KEYS_SHOWN)} more of {hidden} histograms
        </button>
      )}
    </>
  );
}
