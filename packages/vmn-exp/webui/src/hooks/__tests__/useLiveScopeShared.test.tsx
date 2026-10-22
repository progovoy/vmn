/** One live stream per tab (HTTP/1.1 allows 6 connections per host across
 *  every tab): the pages' live subscribers share one connection; the
 *  stream follows their common scope, else the whole app's changes. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render } from "@testing-library/react";
import { useLiveScope, type LiveChange } from "../useLiveScope";
import { FakeSource, lastSource as last } from "./fakeEventSource";

const openSources = () => FakeSource.instances.filter((s) => !s.closed);

function Sub({ app = "my-app", scope, onChange, enabled = true }: {
  app?: string; scope?: string; onChange: (c?: LiveChange) => void; enabled?: boolean;
}) {
  const { connected } = useLiveScope({ ws: "w", app, scope, enabled, onChange });
  return <span data-testid={`sub-${app}-${scope ?? "app"}`}>{connected ? "on" : "off"}</span>;
}

beforeEach(() => {
  FakeSource.instances = [];
  vi.stubGlobal("EventSource", FakeSource);
  sessionStorage.clear();
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("the live stream of a tab", () => {
  it("is one connection for a board and a run page, both told of its changes", () => {
    const board = vi.fn();
    const run = vi.fn();
    const { getByTestId } = render(<><Sub onChange={board} /><Sub scope="0.0.2-dev.t1" onChange={run} /></>);
    expect(openSources()).toHaveLength(1);
    // Different scopes on one app: the app's whole stream.
    expect(last().url).toBe("/api/v1/workspaces/w/apps/my-app/events");
    act(() => last().open());
    expect(getByTestId("sub-my-app-app")).toHaveTextContent("on");
    expect(getByTestId("sub-my-app-0.0.2-dev.t1")).toHaveTextContent("on");
    act(() => last().emit("change", { generation: "2.0", changed: { rows: 1 } }));
    expect(board).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("keeps the common scope of its subscribers", () => {
    render(<><Sub scope="0.0.2-rc.1" onChange={vi.fn()} /><Sub scope="0.0.2-rc.1" onChange={vi.fn()} /></>);
    expect(openSources()).toHaveLength(1);
    expect(last().url).toBe("/api/v1/workspaces/w/apps/my-app/events?scope=0.0.2-rc.1");
  });

  it("follows the newest app on screen; the other app's subscriber polls", () => {
    const { getByTestId } = render(<><Sub app="a" onChange={vi.fn()} /><Sub app="b" onChange={vi.fn()} /></>);
    expect(openSources()).toHaveLength(1);
    act(() => last().open());
    expect(last().url).toContain("/apps/b/events");
    expect(getByTestId("sub-a-app")).toHaveTextContent("off");
    expect(getByTestId("sub-b-app")).toHaveTextContent("on");
  });

  it("narrows back to a scope once the app-wide subscriber leaves, and closes with the last one", async () => {
    const { rerender } = render(<><Sub onChange={vi.fn()} /><Sub scope="0.0.2-rc.1" onChange={vi.fn()} /></>);
    await act(async () => {
      rerender(<><Sub onChange={vi.fn()} enabled={false} /><Sub scope="0.0.2-rc.1" onChange={vi.fn()} /></>);
    });
    expect(openSources()).toHaveLength(1);
    expect(last().url).toBe("/api/v1/workspaces/w/apps/my-app/events?scope=0.0.2-rc.1");
    rerender(<><Sub onChange={vi.fn()} enabled={false} /><Sub scope="0.0.2-rc.1" onChange={vi.fn()} enabled={false} /></>);
    expect(openSources()).toHaveLength(0);
  });
});
