import { describe, it, expect } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { useLeaderboardView } from "../useLeaderboardView";

const where = { search: "" };
function Probe() {
  where.search = useLocation().search;
  return null;
}

function setup(path: string) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[path]}><Probe />{children}</MemoryRouter>
  );
  return renderHook(() => useLeaderboardView(), { wrapper });
}
const url = () => new URLSearchParams(where.search);

describe("one row per group in the URL (plan 34 §1)", () => {
  it("reads collapse_all=1, apart from the folded groups' collapse=", () => {
    const { result } = setup("/b?group=tags.launch_id&collapse_all=1&collapse=1");
    expect(result.current.collapseAll).toBe(true);
    expect([...result.current.collapsed]).toEqual(["1"]);
    expect(setup("/b?group=tags.launch_id").result.current.collapseAll).toBe(false);
  });

  it("is set and cleared by its toggle", () => {
    const { result } = setup("/b?group=tags.launch_id");
    act(() => result.current.setCollapseAll(true));
    expect(url().get("collapse_all")).toBe("1");
    act(() => result.current.setCollapseAll(false));
    expect(url().has("collapse_all")).toBe(false);
  });

  it("is dropped with the grouping", () => {
    const { result } = setup("/b?group=tags.launch_id&collapse_all=1");
    act(() => result.current.setGroup("branch", "none"));
    expect(url().has("collapse_all")).toBe(false);
    act(() => result.current.setCollapseAll(true));
    act(() => result.current.setFilters({ status: "", query: "", search: "", branch: "" }, true));
    expect(url().has("collapse_all")).toBe(false);
  });
});
