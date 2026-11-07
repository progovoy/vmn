/** Publishing a report's panels (plan 13 §6): each live panel renders under
 *  its own query cache, so Publish snapshots exactly what it fetched; a
 *  published panel renders from that snapshot under a frozen cache that
 *  never calls a query function. */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { hashKey, QueryClient, QueryClientProvider, type QueryClientConfig, type QueryKey } from "@tanstack/react-query";
import { createQueryClient } from "../queryClient";

export interface PanelPayload {
  /** Workspace the panel fetched from: its query keys embed it. */
  ws?: string;
  app: string;
  /** The runs the panel showed (the server checks they exist). */
  verstrs: string[];
  /** `vmn://<app>/<verstr>/<path>` of every media file it showed. */
  media: string[];
  queries: { key: QueryKey; data: unknown }[];
}

export interface PanelCapture {
  register: (id: string, ws: string, app: string, client: QueryClient) => () => void;
  collect: () => Record<string, PanelPayload>;
}

const CaptureContext = createContext<PanelCapture | null>(null);

export const usePanelCapture = () => useContext(CaptureContext);

type Entry = { ws: string; app: string; client: QueryClient };

export function PanelCaptureProvider({ children }: { children: ReactNode }) {
  const capture = useMemo<PanelCapture>(() => {
    const panels = new Map<string, Entry>();
    return {
      register: (id, ws, app, client) => {
        panels.set(id, { ws, app, client });
        return () => { if (panels.get(id)?.client === client) panels.delete(id); };
      },
      collect: () => {
        const out: Record<string, PanelPayload> = {};
        for (const [id, { ws, app, client }] of panels) {
          const payload = { ws, ...snapshot(app, client) };
          if (payload.queries.length) out[id] = payload;
        }
        return out;
      },
    };
  }, []);
  return <CaptureContext.Provider value={capture}>{children}</CaptureContext.Provider>;
}

function snapshot(app: string, client: QueryClient): PanelPayload {
  const queries = client.getQueryCache().getAll()
    .filter((q) => q.state.status === "success")
    .map((q) => ({ key: q.queryKey, data: q.state.data }));
  const verstrs = new Set<string>();
  const media = new Set<string>();
  for (const { data } of queries) collectRefs(app, data, verstrs, media);
  return { app, verstrs: [...verstrs], media: [...media], queries };
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);

/** Runs named by a run detail (`metadata.verstr`), a rows page or columns. */
function collectRefs(app: string, data: unknown, verstrs: Set<string>, media: Set<string>) {
  if (!isObj(data)) return;
  const verstr = isObj(data.metadata) ? data.metadata.verstr : undefined;
  if (typeof verstr === "string") {
    verstrs.add(verstr);
    for (const items of Object.values(isObj(data.media) ? data.media : {})) {
      for (const item of Array.isArray(items) ? items : []) {
        if (isObj(item) && typeof item.path === "string") media.add(`vmn://${app}/${verstr}/${item.path}`);
      }
    }
  }
  for (const row of Array.isArray(data.rows) ? data.rows : []) {
    if (isObj(row) && typeof row.verstr === "string") verstrs.add(row.verstr);
  }
  for (const v of Array.isArray(data.verstrs) ? data.verstrs : []) if (typeof v === "string") verstrs.add(v);
}

/** What a frozen cache answers for a query the panel did not capture. */
export class NotPublishedError extends Error {
  constructor() {
    super("not published with this report");
  }
}

/** A cache that answers only from seeded data: queries never run their own
 *  function, a refetch (polling) resolves to the cached value, and a query
 *  without seeded data throws `NotPublishedError` to the nearest boundary. */
class FrozenQueryClient extends QueryClient {
  constructor(config?: QueryClientConfig) {
    super(config);
    const base = this.defaultQueryOptions.bind(this) as (o: unknown) => { queryHash: string; enabled?: unknown };
    // Not getQueryData: it applies these very defaults.
    const seeded = (hash: string) => this.getQueryCache().get(hash)?.state.data;
    const frozen = (options: unknown) => {
      const merged = base(options);
      return {
        ...merged,
        // Only an unseeded query runs, and only when the panel asks for it.
        enabled: seeded(merged.queryHash) === undefined ? merged.enabled ?? true : false,
        retry: false,
        staleTime: Infinity,
        refetchInterval: false,
        throwOnError: (e: unknown) => e instanceof NotPublishedError,
        queryFn: ({ queryKey }: { queryKey: QueryKey }) => {
          const data = seeded(hashKey(queryKey));
          return data === undefined ? Promise.reject(new NotPublishedError()) : data;
        },
      };
    };
    this.defaultQueryOptions = frozen as unknown as QueryClient["defaultQueryOptions"];
  }
}

export function frozenClient(payload: PanelPayload): QueryClient {
  const client = new FrozenQueryClient();
  for (const { key, data } of payload.queries ?? []) client.setQueryData(key, data);
  return client;
}

/** A live panel's own cache, registered for Publish when a capture is open. */
export function LivePanelScope({ id, ws, app, children }: {
  id: string; ws: string; app: string; children: ReactNode;
}) {
  const capture = usePanelCapture();
  const [client] = useState(createQueryClient);
  useEffect(() => (capture && id ? capture.register(id, ws, app, client) : undefined), [capture, id, ws, app, client]);
  if (!capture) return <>{children}</>;
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
