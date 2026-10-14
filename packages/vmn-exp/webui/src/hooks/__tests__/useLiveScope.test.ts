import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLiveScope } from "../useLiveScope";
import { FakeSource, lastSource as last } from "./fakeEventSource";
const setVisibility = (state: DocumentVisibilityState) => {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
};

describe("useLiveScope", () => {
  beforeEach(() => {
    FakeSource.instances = [];
    vi.stubGlobal("EventSource", FakeSource);
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    act(() => setVisibility("visible"));
  });

  const mount = (props: Partial<Parameters<typeof useLiveScope>[0]> = {}) => {
    const onChange = vi.fn();
    const hook = renderHook((p: Parameters<typeof useLiveScope>[0]) => useLiveScope(p), {
      initialProps: { ws: "w", app: "root-svc", enabled: true, onChange, ...props },
    });
    return { ...hook, onChange };
  };

  it("opens the app's event stream, with its scope", () => {
    mount({ scope: "1.0.0-dev.ab" });
    expect(last().url).toBe("/api/v1/workspaces/w/apps/root-svc/events?scope=1.0.0-dev.ab");
  });

  it("is connected once open, and calls onChange on each change event", () => {
    const { result, onChange } = mount();
    expect(result.current.connected).toBe(false);
    act(() => last().open());
    expect(result.current.connected).toBe(true);
    act(() => last().emit("change", { generation: "2.0", changed: { rows: 1 } }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toEqual({ generation: "2.0", changed: { rows: 1 } });
    expect(result.current.lastChangeAt).not.toBeNull();
  });

  it("never overlaps a pending onChange: changes meanwhile make one more call", async () => {
    let settle: () => void = () => {};
    const onChange = vi.fn(() => new Promise<void>((resolve) => { settle = resolve; }));
    mount({ onChange });
    act(() => last().open());
    act(() => {
      last().emit("change", { generation: "2.0", changed: { rows: 1 } });
      last().emit("change", { generation: "3.0", changed: { rows: 1 } });
      last().emit("change", { generation: "4.0", changed: { rows: 1 } });
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    await act(async () => { settle(); });
    expect(onChange).toHaveBeenCalledTimes(2);
    await act(async () => { settle(); });
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("revalidates once when a dropped stream comes back", () => {
    const { onChange } = mount();
    act(() => last().open());
    act(() => last().fail());
    act(() => last().open());
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("falls back (not connected, stream closed) when the server refuses it", () => {
    const { result } = mount();
    act(() => last().fail(true));
    expect(result.current.connected).toBe(false);
    expect(last().closed).toBe(true);
  });

  it("falls back after repeated errors", () => {
    const { result } = mount();
    act(() => last().open());
    act(() => { last().fail(); last().fail(); last().fail(); });
    expect(result.current.connected).toBe(false);
    expect(last().closed).toBe(true);
  });

  it("does not open when disabled (paused) and closes when paused", () => {
    const { rerender, onChange } = mount({ enabled: false });
    expect(FakeSource.instances).toHaveLength(0);
    rerender({ ws: "w", app: "root-svc", enabled: true, onChange });
    expect(FakeSource.instances).toHaveLength(1);
    rerender({ ws: "w", app: "root-svc", enabled: false, onChange });
    expect(last().closed).toBe(true);
  });

  it("closes while the tab is hidden and catches up when it is back", () => {
    const { result, onChange } = mount();
    act(() => last().open());
    act(() => setVisibility("hidden"));
    expect(last().closed).toBe(true);
    expect(result.current.connected).toBe(false);
    act(() => setVisibility("visible"));
    expect(FakeSource.instances).toHaveLength(2);
    act(() => last().open());
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("is never connected where EventSource is missing", () => {
    vi.stubGlobal("EventSource", undefined);
    const { result } = mount();
    expect(result.current.connected).toBe(false);
  });

  it("follows a bearer-token session's stream over fetch, with its Authorization header", async () => {
    sessionStorage.setItem("vmn_token", "t");
    const enc = new TextEncoder();
    let ctl!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start(c) { ctl = c; } });
    const fetchMock = vi.fn(async (_u: string, _i: RequestInit) => new Response(body));
    vi.stubGlobal("fetch", fetchMock);
    const { result, onChange, unmount } = mount({ scope: "top" });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(FakeSource.instances).toHaveLength(0);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/workspaces/w/apps/root-svc/events?scope=top");
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer t");
    expect(result.current.connected).toBe(true);
    await act(async () => {
      ctl.enqueue(enc.encode('event: change\ndata: {"generation":"2.0","changed":{"rows":1}}\n\n'));
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(onChange).toHaveBeenCalledWith({ generation: "2.0", changed: { rows: 1 } });
    const signal = fetchMock.mock.calls[0][1].signal!;
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it("closes on unmount", () => {
    const { unmount } = mount();
    unmount();
    expect(last().closed).toBe(true);
  });
});
