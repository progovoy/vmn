/** A workspace's cache: Resync / Rebuild buttons and the rebuild progress
 *  (plan 11 §4.6). Admin only: renders nothing when the status is refused. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiCache, type CacheStatus } from "../apiCache";

const n = (value: number) => value.toLocaleString("en-US");

export const progressLine = ({ done, total }: CacheStatus["progress"]) =>
  `rebuilding: ${n(done)} / ${n(total)} records`;

export default function CacheResync({ ws }: { ws: string }) {
  const client = useQueryClient();
  const key = ["cache-status", ws];
  const { data } = useQuery({
    queryKey: key,
    queryFn: () => apiCache.status(ws),
    retry: false,
    refetchInterval: (q) => (q.state.data?.state === "rebuilding" ? 1000 : false),
  });
  if (!data) return null;
  const resync = (full: boolean) =>
    apiCache.resync(ws, full).then((status) => client.setQueryData(key, status));
  const rebuilding = data.state === "rebuilding";
  return (
    <aside className="card cache-resync" aria-label="Cache">
      <div className="eyebrow">cache</div>
      <span className="meta">
        {rebuilding ? progressLine(data.progress) : `drift ${n(data.drift)}`}
      </span>{" "}
      <button type="button" disabled={rebuilding} onClick={() => resync(false)}>Resync</button>{" "}
      <button type="button" disabled={rebuilding} onClick={() => resync(true)}>Rebuild</button>
    </aside>
  );
}
