import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useLeaderboardColumns, COMMENTS_COLUMN } from "../useLeaderboardColumns";
import type { ExperimentRow } from "../../types";

const row = (extra: Partial<ExperimentRow> = {}): ExperimentRow => ({
  idx: 1, verstr: "0.0.1", code_verstr: "0.0.1", timestamp: null, note: null,
  branch: "main", base_version: "0.0.1", params: {}, metrics: {}, ...extra,
});
const withComments = [row({ comments: { total: 3, unresolved: 1 } })];

describe("useLeaderboardColumns comments column", () => {
  it("is offered but hidden by default when rows carry comment counts", () => {
    const { result } = renderHook(() => useLeaderboardColumns(withComments, null, new Set(), "", null));
    expect(result.current.otherCols).toContain("comments");
    expect(result.current.visibleOther).not.toContain("comments");
    expect(result.current.layout.ids).not.toContain(COMMENTS_COLUMN);
  });

  it("shows when its hide= key is toggled", () => {
    const hidden = new Set([COMMENTS_COLUMN]);
    const { result } = renderHook(() => useLeaderboardColumns(withComments, null, hidden, "", null));
    expect(result.current.visibleOther).toContain("comments");
    expect(result.current.layout.ids).toContain(COMMENTS_COLUMN);
  });

  it("is not offered when no row carries comment counts", () => {
    const { result } = renderHook(() => useLeaderboardColumns([row()], null, new Set(), "", null));
    expect(result.current.otherCols).not.toContain("comments");
  });
});
