import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLiveOrPoll } from "../useLiveOrPoll";
import { FakeSource, lastSource as last } from "./fakeEventSource";

describe("useLiveOrPoll", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSource.instances = [];
    vi.stubGlobal("EventSource", FakeSource);
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const mount = (props: Partial<Parameters<typeof useLiveOrPoll>[0]> = {}) => {
    const refresh = vi.fn();
    const hook = renderHook((p: Parameters<typeof useLiveOrPoll>[0]) => useLiveOrPoll(p), {
      initialProps: { ws: "w", app: "a", scope: "top", enabled: true, heartbeatSec: 5, refresh, ...props },
    });
    return { ...hook, refresh };
  };

  it("polls at the heartbeat cadence until the stream opens", () => {
    const { refresh, result } = mount();
    act(() => { vi.advanceTimersByTime(5000); });
    expect(refresh).toHaveBeenCalledTimes(1);
    act(() => last().open());
    expect(result.current).toBe(true);
    act(() => { vi.advanceTimersByTime(20000); });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("refreshes on each change event, scoped", () => {
    const { refresh } = mount();
    expect(last().url).toContain("?scope=top");
    act(() => last().open());
    act(() => last().emit("change", { generation: "2", changed: { rows: 1 } }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("neither listens nor polls while disabled", () => {
    const { refresh, result } = mount({ enabled: false });
    expect(FakeSource.instances).toHaveLength(0);
    act(() => { vi.advanceTimersByTime(20000); });
    expect(refresh).not.toHaveBeenCalled();
    expect(result.current).toBe(false);
  });
});
