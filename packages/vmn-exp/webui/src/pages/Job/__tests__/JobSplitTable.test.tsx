/** Plan 28 P3: the Overview's per-value table under the KPI tiles, each
 *  cell a link to the Runs tab filtered by its value's clause. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../apiJob", () => ({ jobSummary: vi.fn(), jobFailures: vi.fn(), jobImportance: vi.fn() }));

import { jobFailures } from "../../../apiJob";
import type { JobPageSummary, JobSplitEntry } from "../../../apiJob";
import JobOverview from "../JobOverview";
import { failuresFixture, JOB, jobSummaryFixture } from "./jobFixture";

const RUN = `/ws/test/app/my-app/run/${JOB}`;

function entry(over: Partial<JobSplitEntry>): JobSplitEntry {
  return {
    key: "trial", label: "trial", clause: 'tags.kind = "trial"', total: 1900,
    counts: { running: 10, waiting: 0, succeeded: 1888, failed: 2, stuck: 0 },
    done: 1890, never_started: 0, lost: 0, failed_pct: 0.11,
    duration: { n: 1890, p50: 120, p90: 300 },
    ...over,
  };
}

const BY: JobSplitEntry[] = [
  entry({}),
  entry({
    key: "refit", label: "refit", clause: 'tags.kind = "refit"', total: 60,
    counts: { running: 2, waiting: 40, succeeded: 18, failed: 0, stuck: 0 }, done: 18, failed_pct: 0,
    duration: { n: 18, p50: 3600, p90: 7200 },
  }),
  entry({ key: null, label: "other", other: true, clause: null, total: 40, done: 40, duration: { n: 0, p50: null, p90: null } }),
];

function renderOverview(summary: JobPageSummary) {
  return renderWithClient(
    <MemoryRouter><JobOverview ws="test" app="my-app" summary={summary} /></MemoryRouter>,
  );
}

const hrefOf = (link: HTMLElement) => new URL(link.getAttribute("href")!, "http://x");

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(jobFailures).mockResolvedValue(failuresFixture());
});

describe("job overview split table", () => {
  it("is absent without a split", () => {
    renderOverview(jobSummaryFixture());
    expect(screen.queryByRole("table", { name: /^Runs by/ })).not.toBeInTheDocument();
  });

  it("shows a row per value, named by the split field", () => {
    renderOverview(jobSummaryFixture({ split: "tags.kind", by: BY }));
    const table = screen.getByRole("table", { name: "Runs by tags.kind" });
    const rows = within(table).getAllByRole("row");
    expect(within(rows[0]).getAllByRole("columnheader").map((c) => c.textContent))
      .toEqual(["tags.kind", "runs", "done", "failed", "running", "waiting", "p50", "p90"]);
    expect(rows).toHaveLength(4);
    expect(within(rows[1]).getAllByRole("cell").map((c) => c.textContent))
      .toEqual(["trial", "1,900", "1,890", "2", "10", "0", "2m", "5m"]);
    expect(within(rows[2]).getAllByRole("cell").map((c) => c.textContent))
      .toEqual(["refit", "60", "18", "0", "2", "40", "1h", "2h"]);
  });

  it("links each cell to the job's runs of that value, the counts by status", () => {
    renderOverview(jobSummaryFixture({ split: "tags.kind", by: BY }));
    const table = screen.getByRole("table", { name: "Runs by tags.kind" });
    const refit = within(table).getAllByRole("row")[2];
    const value = hrefOf(within(refit).getByRole("link", { name: "refit" }));
    expect(value.pathname).toBe(RUN);
    expect(value.searchParams.get("tab")).toBe("runs");
    expect(value.searchParams.get("q")).toBe('tags.kind = "refit"');
    expect(value.searchParams.has("status")).toBe(false);
    const waiting = hrefOf(within(refit).getByRole("link", { name: "40 refit runs waiting" }));
    expect(waiting.searchParams.get("status")).toBe("created");
    expect(waiting.searchParams.get("q")).toBe('tags.kind = "refit"');
    const failed = hrefOf(within(refit).getByRole("link", { name: "0 refit runs failed" }));
    expect(failed.searchParams.get("status")).toBe("failed,stuck");
  });

  it("does not link a value the query language cannot select", () => {
    renderOverview(jobSummaryFixture({ split: "tags.kind", by: BY }));
    const table = screen.getByRole("table", { name: "Runs by tags.kind" });
    const other = within(table).getAllByRole("row")[3];
    expect(within(other).queryAllByRole("link")).toHaveLength(0);
    expect(within(other).getAllByRole("cell")[0]).toHaveTextContent("other");
    expect(within(other).getAllByRole("cell")[6]).toHaveTextContent("—");
  });
});
