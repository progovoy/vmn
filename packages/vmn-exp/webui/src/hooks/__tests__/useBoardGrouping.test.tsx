import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { createQueryClient } from "../../queryClient";

vi.mock("../../api", () => ({
  api: { facets: vi.fn(), config: vi.fn() },
}));

import { api } from "../../api";
import { useBoardGrouping } from "../useBoardGrouping";
import { useLeaderboardView } from "../useLeaderboardView";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const facets = (extra = {}) => ({
  branches: ["main"], metric_keys: ["loss"], param_keys: ["lr"], tag_keys: [],
  param_values: { lr: 3 }, parented: 0, total: 3, ...extra,
});
const notFound = () => Object.assign(new Error("nf"), { status: 404 });

const where = { search: "" };
function Probe() {
  where.search = useLocation().search;
  return null;
}

function setup(path = "/b") {
  const client = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}><Probe />{children}</MemoryRouter>
    </QueryClientProvider>
  );
  return renderHook(() => {
    const view = useLeaderboardView();
    return { view, grouping: useBoardGrouping("w", "app", view) };
  }, { wrapper });
}
const url = () => new URLSearchParams(where.search);

beforeEach(() => {
  vi.clearAllMocks();
  m.facets.mockResolvedValue(facets());
  m.config.mockRejectedValue(notFound());
});

describe("the board's grouping (plan 22 G2, G10)", () => {
  it("is unknown until the facets arrive, then parent for an app with parented runs", async () => {
    m.facets.mockResolvedValue(facets({ parented: 3 }));
    const { result } = setup();
    expect(result.current.grouping.group).toBeNull();
    await waitFor(() => expect(result.current.grouping.group).toBe("parent"));
    expect(result.current.grouping.defaultGroup).toBe("parent");
  });

  it("is none for an app without parented runs, and when the facets fail", async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.grouping.group).toBe("none"));
    m.facets.mockRejectedValue(notFound());
    const failed = setup();
    await waitFor(() => expect(failed.result.current.grouping.group).toBe("none"));
  });

  it("follows ?group= at once, without waiting for the facets", () => {
    m.facets.mockImplementation(() => new Promise(() => {}));
    const { result } = setup("/b?group=params.lr");
    expect(result.current.grouping.group).toBe("params.lr");
  });

  it("ignores an unknown ?group= (the default applies)", async () => {
    const { result } = setup("/b?group=inputs");
    await waitFor(() => expect(result.current.grouping.group).toBe("none"));
  });

  it("writes group= only away from the default, and none explicitly", async () => {
    m.facets.mockResolvedValue(facets({ parented: 3 }));
    const { result } = setup();
    await waitFor(() => expect(result.current.grouping.group).toBe("parent"));
    act(() => result.current.grouping.setGroup("branch"));
    expect(url().get("group")).toBe("branch");
    expect(result.current.grouping.group).toBe("branch");
    act(() => result.current.grouping.setGroup("none"));
    expect(url().get("group")).toBe("none");
    act(() => result.current.grouping.setGroup("parent"));
    expect(url().has("group")).toBe(false);
  });

  it("aggregates by the mean unless the URL or the app's conf says otherwise", async () => {
    const { result } = setup();
    await waitFor(() => expect(m.config).toHaveBeenCalled());
    expect(result.current.grouping.aggregate).toBe("mean");
    expect(result.current.grouping.aggregateInUrl).toBeNull();

    m.config.mockResolvedValue({ conf: { experiment: { ui: { group_aggregate: "median" } } }, text: "" });
    const conf = setup();
    await waitFor(() => expect(conf.result.current.grouping.aggregate).toBe("median"));
    expect(conf.result.current.grouping.defaultAggregate).toBe("median");

    const fromUrl = setup("/b?agg=best");
    expect(fromUrl.result.current.grouping.aggregate).toBe("best");
    expect(fromUrl.result.current.grouping.aggregateInUrl).toBe("best");
  });

  it("writes agg= only away from the default; a bad agg= is ignored", async () => {
    m.config.mockResolvedValue({ conf: { experiment: { ui: { group_aggregate: "max" } } }, text: "" });
    const { result } = setup("/b?agg=sum");
    await waitFor(() => expect(result.current.grouping.aggregate).toBe("max"));
    act(() => result.current.grouping.setAggregate("min"));
    expect(url().get("agg")).toBe("min");
    act(() => result.current.grouping.setAggregate("max"));
    expect(url().has("agg")).toBe(false);
  });

  it("remembers closed groups in collapse=, and a new grouping opens them all", async () => {
    const { result } = setup("/b?group=branch");
    act(() => result.current.view.toggleCollapsed("main"));
    act(() => result.current.view.toggleCollapsed("dev"));
    expect(url().getAll("collapse")).toEqual(["main", "dev"]);
    expect([...result.current.view.collapsed]).toEqual(["main", "dev"]);
    act(() => result.current.view.toggleCollapsed("main"));
    expect(url().getAll("collapse")).toEqual(["dev"]);
    act(() => result.current.grouping.setGroup("status"));
    expect(url().getAll("collapse")).toEqual([]);
  });

  it("round-trips a grouped view through its URL", async () => {
    const { result } = setup("/b?group=tags.team&agg=median&collapse=a");
    expect(result.current.grouping.group).toBe("tags.team");
    expect(result.current.grouping.aggregate).toBe("median");
    expect([...result.current.view.collapsed]).toEqual(["a"]);
  });

  it("maps nothing from expand= onto groups (G8)", async () => {
    const { result } = setup("/b?group=parent&expand=0.0.1-dev.x");
    expect(result.current.view.collapsed.size).toBe(0);
    act(() => result.current.view.toggleCollapsed("0.0.1-dev.x"));
    expect(url().getAll("collapse")).toEqual(["0.0.1-dev.x"]);
  });
});
