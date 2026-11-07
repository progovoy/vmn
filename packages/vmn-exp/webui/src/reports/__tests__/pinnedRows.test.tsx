/** Plan 32 audit: a pinned-runs panel labels each run by its own `@N` (the
 *  run detail's `idx`), never by its position in the panel; a run the
 *  server has not indexed yet reads its verstr. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn() },
  appTag: (a: string) => a.replaceAll("/", "-"),
}));

import { api } from "../../api";
import Panel from "../Panel";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const detail = (verstr: string, idx: number | null) =>
  ({ metadata: { verstr }, idx, metrics: { loss: 0.5 }, params: {}, series: {} });

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.experiment.mockImplementation(async (_ws: string, _app: string, v: string) =>
    detail(v, v === "a" ? 42 : null));
});

describe("a pinned leaderboard panel", () => {
  it("labels a run by its idx, and an unindexed one by its verstr", async () => {
    renderWithClient(
      <MemoryRouter>
        <Panel ws="w" spec={{ v: 1, id: "p", app: "my_app", type: "leaderboard",
          runs: { verstrs: ["a", "b"] }, columns: ["loss"] }} />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: "@42" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "b" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^@[12]$/ })).toBeNull();
  });
});
