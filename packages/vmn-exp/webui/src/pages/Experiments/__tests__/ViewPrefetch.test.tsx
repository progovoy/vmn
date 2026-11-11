/** Which first pages the experiments page prefetches for the views it does
 *  not show (useViewPrefetch's viewFilters). */
import { describe, it, expect } from "vitest";
import type { useLeaderboardView } from "../../../hooks/useLeaderboardView";
import { viewFilters } from "../useViewPrefetch";

type View = ReturnType<typeof useLeaderboardView>;
const VIEW = { sort: null, status: "", query: "", search: "", branch: "", archived: false } as unknown as View;

describe("viewFilters", () => {
  it("a singles-only app prefetches All runs and no top page", () => {
    const filters = viewFilters(VIEW, "singles");
    expect(Object.keys(filters).sort()).toEqual(["all", "singles"]);
    expect(filters.singles).toEqual(expect.objectContaining({ top: "singles" }));
    expect(filters.all?.top).toBeUndefined();
  });

  it("an app with outer runs prefetches each side and All runs", () => {
    expect(Object.keys(viewFilters(VIEW, "jobs")).sort()).toEqual(["all", "jobs", "singles"]);
  });

  it("an app of unknown shape prefetches the top-level runs and All runs", () => {
    const filters = viewFilters(VIEW, "top");
    expect(Object.keys(filters).sort()).toEqual(["all", "top"]);
    expect(filters.top).toEqual(expect.objectContaining({ top: true }));
  });
});
