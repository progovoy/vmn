/** Plan 34 §3: lost is its own state. A lost run (stuck under an ended outer
 *  run) reads `stuck · lost`; a tree whose only bad runs are lost reads its
 *  own status plus the count, `succeeded · 1 lost`, on the board, the tree
 *  and the run page. */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import StatusPill from "../StatusPill";
import RunHead from "../../pages/RunHead";
import type { RunStatus } from "../../types";
import type { RunSummary } from "../../pages/runSummary";

const pill = () => document.querySelector(".status-pill") as HTMLElement;

describe("a lost run's pill", () => {
  it("reads stuck · lost, its label why", () => {
    render(<StatusPill status="stuck" settled="lost" />);
    expect(pill().className).toBe("status-pill stuck");
    expect(pill().textContent).toContain("stuck · lost");
    expect(pill().getAttribute("title")).toContain("· lost: its outer run ended");
  });
});

describe("a tree's lost count", () => {
  it("reads beside its status", () => {
    render(<StatusPill status="succeeded" lost={1} />);
    expect(pill().textContent).toBe("succeeded · 1 lost");
    expect(pill().getAttribute("title")).toBe("succeeded · 1 lost");
  });

  it("is left out at none", () => {
    render(<StatusPill status="succeeded" lost={0} />);
    expect(pill().textContent).toBe("succeeded");
  });
});

const summary = (status: Partial<RunStatus>): RunSummary => ({
  verstr: "0.0.1-dev.o", name: null, tags: {}, branch: null, idx: 2, baseVersion: null, note: null,
  status: status as RunStatus, metrics: {}, params: null,
});

describe("the run page of an outer run with lost runs", () => {
  it("reads its tree status and the lost count", () => {
    const fleet = { expected: 3, counts: { succeeded: 2, failed: 0, running: 0, stuck: 0, created: 0, waiting: 0 },
      never_started: 0, lost: 1, children: [] };
    render(
      <MemoryRouter>
        <RunHead ws="w" app="a" runUrl={(v) => v} actions={null}
          summary={summary({ status: "succeeded", tree_status: "succeeded", kind: "outer", fleet } as Partial<RunStatus>)} />
      </MemoryRouter>,
    );
    expect(pill().textContent).toBe("succeeded · 1 lost");
  });
});
