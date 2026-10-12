/** Lazy chunks of an older build that are gone from the server. Vite's
 *  preload helper reports each failed dynamic import as a `vite:preloadError`
 *  event carrying the error it then throws, so the error is marked at its
 *  source and RouteError never guesses from a browser's wording. */
const stale = new WeakSet<object>();

/** Start marking; returns the function that stops. main.tsx calls it once. */
export function watchStaleChunks(): () => void {
  const mark = (e: Event) => {
    const error = (e as Event & { payload?: unknown }).payload;
    if (typeof error === "object" && error !== null) stale.add(error);
  };
  window.addEventListener("vite:preloadError", mark);
  return () => window.removeEventListener("vite:preloadError", mark);
}

export const isStaleChunk = (error: unknown): boolean =>
  typeof error === "object" && error !== null && stale.has(error);
