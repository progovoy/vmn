/** An abort signal scoped to the synchronous start of a request.
 *
 *  `withSignal(signal, () => api.experiments(...))` makes the fetch inside
 *  carry *signal* without threading it through every api signature (callers
 *  and their tests keep calling `api.x(...)` exactly as before). It works
 *  because `fetch` is invoked synchronously when an api function is called,
 *  before its first `await`. */

let scoped: AbortSignal | undefined;

export function withSignal<T>(signal: AbortSignal, fn: () => T): T {
  const previous = scoped;
  scoped = signal;
  try {
    return fn();
  } finally {
    scoped = previous;
  }
}

export function currentSignal(): AbortSignal | undefined {
  return scoped;
}

export function isAbortError(e: unknown): boolean {
  return (e as { name?: string } | null)?.name === "AbortError";
}
