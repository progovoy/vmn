import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetadataCard } from "../RunSections";
import type { ExperimentDetail } from "../../types";

const detail = (compacted: boolean | null | undefined): ExperimentDetail => ({
  metadata: { verstr: "1.0.0-dev.a", branch: "main" },
  metrics: {},
  series: {},
  patches: {},
  compacted,
});

describe("not compacted badge", () => {
  it("shows on a run whose metrics are still streams", () => {
    render(<MetadataCard detail={detail(false)} />);
    expect(screen.getByText("not compacted")).toBeTruthy();
  });

  it("is absent once compacted, or when the run has no metric files", () => {
    for (const compacted of [true, null, undefined]) {
      const { unmount } = render(<MetadataCard detail={detail(compacted)} />);
      expect(screen.queryByText("not compacted")).toBeNull();
      unmount();
    }
  });
});
