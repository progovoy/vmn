/** Slow per-run requests (run detail, series, log, patch, baselines, media,
 *  tables, histograms: per-run store reads, S3 on a remote store) take at
 *  most 2 of the browser's 6 connections per host (HTTP/1.1, shared by every
 *  tab), the page on screen first; index-backed requests never wait behind
 *  them, and an aborted one never holds a connection. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { get, post } from "../http";
import { createQueryClient } from "../queryClient";
import { isAbortError, withSignal } from "../requestScope";
import { PatchChanges } from "../components/RunChangesBody";
import RunChanges from "../components/RunChanges";
import { MemoryRouter } from "react-router-dom";

type Call = { url: string; signal?: AbortSignal; resolve: (body: unknown) => void };
let calls: Call[] = [];
const inFlight = () => calls.filter((c) => !c.signal?.aborted && !(c as { done?: boolean }).done);

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit) => new Promise((resolve, reject) => {
    const call: Call & { done?: boolean } = {
      url, signal: init.signal ?? undefined,
      resolve: (body) => { call.done = true; resolve(new Response(JSON.stringify(body))); },
    };
    init.signal?.addEventListener("abort", () => {
      call.done = true;
      reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
    });
    calls.push(call);
  })));
  window.history.replaceState(null, "", "/ws/w/app/a/run/v1");
});
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
afterEach(async () => {
  // The gate is the tab's: let every request of this test end.
  for (let i = 0; i < 20 && inFlight().length; i += 1) {
    inFlight().forEach((c) => c.resolve({}));
    await flush();
  }
  vi.unstubAllGlobals();
});

const A = "/workspaces/w/apps/a";
const fetched = () => calls.map((c) => c.url.replace("/api/v1", ""));

describe("the slow request gate", () => {
  it("lets 2 slow requests in flight at once, the next one as each ends", async () => {
    const urls = [`${A}/experiments/v1`, `${A}/experiments/v1/log?offset=0`, `${A}/experiments/v1/patch`,
      `${A}/experiments/v1/baselines`, `${A}/experiments/v1/table/t.json?offset=0`,
      `${A}/experiments/v1/histograms/w`];
    urls.forEach((u) => void get(u));
    void post(`${A}/series`, { verstrs: ["v1"] });
    await flush();
    expect(inFlight()).toHaveLength(2);
    expect(fetched()).toEqual(urls.slice(0, 2));
    calls[0].resolve({});
    await flush();
    expect(inFlight()).toHaveLength(2);
    expect(fetched()).toHaveLength(3);
  });

  it("never holds back index-backed requests", async () => {
    void get(`${A}/experiments/v1`);
    void get(`${A}/experiments/v2`);
    void get(`${A}/experiments/v3`);
    void get(`${A}/experiments?offset=0&limit=50`);
    void get(`${A}/experiments-facets`);
    void get(`${A}/experiments-status`);
    void get(`${A}/experiments-columns?keys=x`);
    void get(`${A}/experiments/v1/summary`);
    await flush();
    expect(fetched()).toEqual([
      `${A}/experiments/v1`, `${A}/experiments/v2`, `${A}/experiments?offset=0&limit=50`,
      `${A}/experiments-facets`, `${A}/experiments-status`, `${A}/experiments-columns?keys=x`,
      `${A}/experiments/v1/summary`,
    ]);
  });

  it("drops a waiting request once aborted, and frees the slot of an aborted one", async () => {
    const one = new AbortController();
    const waiting = new AbortController();
    void withSignal(one.signal, () => get(`${A}/experiments/v1`)).catch(() => {});
    void get(`${A}/experiments/v2`);
    const dropped = withSignal(waiting.signal, () => get(`${A}/experiments/v3`));
    void get(`${A}/experiments/v4`);
    await flush();
    waiting.abort();
    await expect(dropped).rejects.toSatisfy(isAbortError);
    one.abort();
    await flush();
    expect(fetched()).toEqual([`${A}/experiments/v1`, `${A}/experiments/v2`, `${A}/experiments/v4`]);
  });

  it("starts the page on screen's waiting requests first", async () => {
    void get(`${A}/experiments/v1`);
    void get(`${A}/experiments/v2`);
    void get(`${A}/experiments/old`);
    window.history.pushState(null, "", "/ws/w/app/a/run/v9");
    void get(`${A}/experiments/v9`);
    await flush();
    calls[0].resolve({});
    await flush();
    expect(fetched()[2]).toBe(`${A}/experiments/v9`);
  });
});

describe("a run page's sections", () => {
  const wrap = (ui: JSX.Element) => (
    <QueryClientProvider client={createQueryClient()}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>
  );

  it("abort their patch and baselines requests once unmounted", async () => {
    const { unmount } = render(wrap(<>
      <PatchChanges ws="w" app="a" verstr="v1" />
      <RunChanges ws="w" app="a" verstr="v1" baseline={null} onBaseline={() => {}} />
    </>));
    await waitFor(() => expect(calls).toHaveLength(2));
    unmount();
    expect(calls.every((c) => c.signal?.aborted)).toBe(true);
  });
});
