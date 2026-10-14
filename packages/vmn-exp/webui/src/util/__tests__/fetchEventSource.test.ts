import { describe, it, expect, vi, afterEach } from "vitest";
import { FetchEventSource, SseParser } from "../fetchEventSource";

/** A fetch answer whose body yields *chunks*, then ends (or stays open). */
function streamed(chunks: string[], { open = false, status = 200 } = {}) {
  const enc = new TextEncoder();
  let ctl: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      ctl = c;
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      if (!open) c.close();
    },
  });
  return { response: new Response(body, { status }), push: (s: string) => ctl.enqueue(enc.encode(s)) };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("SseParser", () => {
  it("parses event, multi-line data, comments and retry across chunk boundaries", () => {
    const got: [string, string][] = [];
    const retries: number[] = [];
    const p = new SseParser((type, data) => got.push([type, data]), (ms) => retries.push(ms));
    p.feed(": heartbeat\r\nevent: cha");
    p.feed("nge\ndata: {\"a\":\ndata:1}\n\n");
    p.feed("data: plain\r\rretry: 1500\nretry: x\n\n");
    expect(got).toEqual([["change", "{\"a\":\n1}"], ["message", "plain"]]);
    expect(retries).toEqual([1500]);
  });

  it("dispatches nothing for an event without data", () => {
    const got: string[] = [];
    const p = new SseParser((type) => got.push(type), () => {});
    p.feed("event: change\n\n");
    expect(got).toEqual([]);
  });
});

describe("FetchEventSource", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("sends the headers, opens, and dispatches named events", async () => {
    const { response, push } = streamed([], { open: true });
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => response);
    vi.stubGlobal("fetch", fetchMock);
    const src = new FetchEventSource("/events", { Authorization: "Bearer t" });
    const onopen = vi.fn();
    const changes: unknown[] = [];
    src.onopen = onopen;
    src.addEventListener("change", (e) => changes.push(JSON.parse(e.data)));
    await flush();
    expect(fetchMock.mock.calls[0][0]).toBe("/events");
    const headers = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(headers.get("Authorization")).toBe("Bearer t");
    expect(headers.get("Accept")).toBe("text/event-stream");
    expect(onopen).toHaveBeenCalledTimes(1);
    expect(src.readyState).toBe(FetchEventSource.OPEN);
    push("event: change\ndata: {\"generation\":\"2\"}\n\n");
    await flush();
    expect(changes).toEqual([{ generation: "2" }]);
    src.close();
  });

  it("reconnects with backoff after the stream ends, honouring retry:", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => streamed(["retry: 2000\n\n"]).response);
    vi.stubGlobal("fetch", fetchMock);
    const src = new FetchEventSource("/events", {});
    const onerror = vi.fn();
    src.onerror = onerror;
    await vi.advanceTimersByTimeAsync(0);
    expect(onerror).toHaveBeenCalledTimes(1);
    expect(src.readyState).toBe(FetchEventSource.CONNECTING);
    await vi.advanceTimersByTimeAsync(1999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    src.close();
  });

  it("backs off longer after each failure in a row", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => { throw new TypeError("network"); });
    vi.stubGlobal("fetch", fetchMock);
    const src = new FetchEventSource("/events", {});
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1999);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    src.close();
  });

  it("closes for good when the server refuses the stream", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("no", { status: 503 })));
    const src = new FetchEventSource("/events", {});
    const onerror = vi.fn();
    src.onerror = onerror;
    await flush();
    expect(onerror).toHaveBeenCalledTimes(1);
    expect(src.readyState).toBe(FetchEventSource.CLOSED);
  });

  it("aborts the request on close and never reconnects", async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    const fetchMock = vi.fn(async (_u: string, init: RequestInit) => {
      signal = init.signal ?? undefined;
      return streamed([], { open: true }).response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const src = new FetchEventSource("/events", {});
    const onerror = vi.fn();
    src.onerror = onerror;
    await vi.advanceTimersByTimeAsync(0);
    src.close();
    expect(signal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onerror).not.toHaveBeenCalled();
    expect(src.readyState).toBe(FetchEventSource.CLOSED);
  });
});
