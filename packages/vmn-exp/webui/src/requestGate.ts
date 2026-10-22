/** A tab's slow per-run requests, at most `SLOW_LIMIT` in flight.
 *
 *  Over plain HTTP a browser keeps 6 connections per host for all its tabs
 *  together. A run's detail, series, log, patch, baselines, media, tables
 *  and histograms are per-run store reads (seconds each on S3); unchecked,
 *  a few of them queue the index-backed requests (lists, facets, status,
 *  columns, summaries: milliseconds) behind them for minutes. Waiting
 *  requests start first-in first-out, the page on screen's before others;
 *  an aborted one leaves the queue at once, so it never takes a connection. */

export const SLOW_LIMIT = 2;

const APP = "^/workspaces/[^/]+/apps/[^/]+/";
const SLOW_GET = new RegExp(
  `${APP}experiments/[^/?]+((/(log|patch|baselines|media|table|histograms))([/?].*)?|\\?.*)?$`,
);
const SLOW_POST = new RegExp(`${APP}series$`);

/** Whether *method* *path* (under the API base) is a slow per-run read;
 *  writes are never held back. */
export const isSlow = (method: string, path: string) =>
  (method === "GET" && SLOW_GET.test(path)) || (method === "POST" && SLOW_POST.test(path));

type Waiter = { page: string; start: () => void };

let running = 0;
let waiting: Waiter[] = [];

const page = () => window.location.pathname;

function next() {
  if (running >= SLOW_LIMIT || waiting.length === 0) return;
  const here = page();
  const w = waiting.find((x) => x.page === here) ?? waiting[0];
  waiting = waiting.filter((x) => x !== w);
  w.start();
}

const abortError = () => Object.assign(new Error("The request was aborted."), { name: "AbortError" });

/** *send* once a slot is free; rejects (unsent) when *signal* aborts first. */
export function gated<T>(signal: AbortSignal | undefined, send: () => Promise<T>): Promise<T> {
  if (signal?.aborted) return Promise.reject(abortError());
  return new Promise<T>((resolve, reject) => {
    const w: Waiter = {
      page: page(),
      start: () => {
        signal?.removeEventListener("abort", drop);
        running += 1;
        send().then(resolve, reject).finally(() => {
          running -= 1;
          next();
        });
      },
    };
    function drop() {
      waiting = waiting.filter((x) => x !== w);
      reject(abortError());
    }
    signal?.addEventListener("abort", drop, { once: true });
    waiting.push(w);
    next();
  });
}
