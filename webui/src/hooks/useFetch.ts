import { useCallback, useEffect, useRef, useState } from "react";

export function useFetch<T>(url: string | null, opts?: RequestInit) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(url !== null);
  const abortRef = useRef<AbortController | null>(null);

  const doFetch = useCallback(async () => {
    if (!url) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(url, { ...opts, signal: ctrl.signal });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const json = await res.json();
      if (!ctrl.signal.aborted) {
        setData(json);
        setLoading(false);
      }
    } catch (e: any) {
      if (e.name !== "AbortError" && !ctrl.signal.aborted) {
        setError(e);
        setLoading(false);
      }
    }
  }, [url]);

  useEffect(() => {
    if (url === null) { setLoading(false); return; }
    doFetch();
    return () => { abortRef.current?.abort(); };
  }, [url, doFetch]);

  return { data, error, loading, refetch: doFetch };
}
