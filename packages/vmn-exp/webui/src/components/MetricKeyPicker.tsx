import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useDebounce } from "../hooks/useDebounce";
import type { MetricKeysPage, MetricKeysQuery } from "../apiRun";

/** Keys fetched per page of `.../metric-keys`. */
export const KEYS_PAGE = 200;
const ROW_H = 24;

interface Loaded {
  prefix: string;
  names: string[];
  total: number;
}

/** A searchable, virtualized list of a run's metric names for runs with
 *  thousands of them: names arrive a page at a time from the server
 *  (*fetchPage*, searched by prefix there) as the list is scrolled, and
 *  only the visible rows are rendered. Checking a name toggles its chart. */
export default function MetricKeyPicker({ fetchPage, selected, onToggle }: {
  fetchPage: (q: MetricKeysQuery) => Promise<MetricKeysPage>;
  selected: string[];
  onToggle: (name: string) => void;
}) {
  const [query, setQuery] = useState("");
  const prefix = useDebounce(query, 200);
  const [loaded, setLoaded] = useState<Loaded>({ prefix, names: [], total: 0 });
  const pending = useRef<string | null>(null);
  const parentRef = useRef<HTMLDivElement>(null);

  const load = (forPrefix: string, offset: number) => {
    const id = `${forPrefix}\u0000${offset}`;
    if (pending.current === id) return;
    pending.current = id;
    fetchPage({ prefix: forPrefix, offset, limit: KEYS_PAGE }).then((page) => {
      if (pending.current !== id) return;
      pending.current = null;
      setLoaded((prev) => ({
        prefix: forPrefix,
        names: offset === 0 || prev.prefix !== forPrefix
          ? page.keys.map((k) => k.name)
          : [...prev.names, ...page.keys.map((k) => k.name)],
        total: page.total,
      }));
    }, () => { if (pending.current === id) pending.current = null; });
  };

  useEffect(() => { load(prefix, 0); }, [prefix, fetchPage]);

  const names = loaded.prefix === prefix ? loaded.names : [];
  const v = useVirtualizer({
    count: names.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_H,
    overscan: 20,
  });
  const items = v.getVirtualItems();
  const lastShown = items.length ? items[items.length - 1].index : -1;
  const more = names.length > 0 && names.length < loaded.total && lastShown >= names.length - 1;
  useEffect(() => { if (more) load(prefix, names.length); }, [more, prefix, names.length]);

  const chosen = new Set(selected);
  return (
    <div className="metric-key-picker" style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, fontSize: 12 }}>
        <input
          type="search" aria-label="metric keys" placeholder="search metrics by prefix"
          value={query} onChange={(e) => setQuery(e.target.value)}
        />
        <span style={{ color: "var(--text-3)" }}>
          {loaded.total} metrics · {selected.length} charted
        </span>
      </div>
      <div ref={parentRef} style={{ maxHeight: 240, overflowY: "auto" }}>
        <div style={{ height: v.getTotalSize(), position: "relative" }}>
          {items.map((item) => {
            const name = names[item.index];
            return (
              <label
                key={item.key} className="mono"
                style={{ position: "absolute", top: item.start, left: 0, right: 0, height: ROW_H, fontSize: 12 }}
              >
                <input
                  type="checkbox" aria-label={name} checked={chosen.has(name)}
                  onChange={() => onToggle(name)}
                />{" "}
                {name}
              </label>
            );
          })}
        </div>
      </div>
    </div>
  );
}
