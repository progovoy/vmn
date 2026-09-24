import { useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";

/** Replace every value of the repeated param *name* in *p*. */
export function setAllParams(p: URLSearchParams, name: string, values: readonly string[]) {
  p.delete(name);
  values.forEach((v) => p.append(name, v));
}

/** View state kept in the query string, so a view is shareable and Back
 *  restores it. Every update *merges* into the current params (replacing the
 *  history entry), several updates in one tick compose, and an update that
 *  changes nothing does not navigate at all. */
export function useUrlState() {
  const [params, setSearchParams] = useSearchParams();
  // The router recreates its setter on every URL change; ours stays stable so
  // callers can list it as an effect dependency.
  const setRef = useRef(setSearchParams);
  setRef.current = setSearchParams;
  const latest = useRef(params);
  const seen = useRef(params.toString());
  // Adopt the URL only when it really moved: a render between our own
  // navigate and the router catching up must not roll `latest` back.
  if (params.toString() !== seen.current) {
    seen.current = params.toString();
    latest.current = params;
  }

  const update = useCallback(
    (edit: (p: URLSearchParams) => void) => {
      const next = new URLSearchParams(latest.current);
      edit(next);
      if (next.toString() === latest.current.toString()) return;
      latest.current = next;
      setRef.current(next, { replace: true });
    },
    [],
  );

  const setParam = useCallback(
    (name: string, value: string | null | undefined) =>
      update((p) => (value ? p.set(name, value) : p.delete(name))),
    [update],
  );

  return { params, update, setParam };
}
