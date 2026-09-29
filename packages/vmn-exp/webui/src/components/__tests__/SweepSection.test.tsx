import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ExperimentRow } from "../../types";
import { SweepCard, bestTrial, sweepSpecOf, type SweepSpec } from "../SweepSection";

const spec: SweepSpec = {
  method: "random",
  metric: { name: "loss", goal: "min" },
  parameters: {
    lr: { distribution: "log_uniform", min: 0.0001, max: 0.1 },
    bs: { values: [16, 32] },
    opt: { value: "adam" },
  },
  run_cap: 20,
  early_terminate: { type: "median", min_iter: 3 },
};

function row(trial: number, status: string, loss: number | null, extra: Partial<ExperimentRow> = {}): ExperimentRow {
  return {
    idx: trial + 2,
    verstr: `0.0.1-dev.aaa.bbb.r${trial + 2}`,
    code_verstr: "0.0.1-dev.aaa.bbb",
    timestamp: null, note: null, branch: null, base_version: null, user_meta: null,
    name: `sw-t${trial}`,
    status: status as ExperimentRow["status"],
    params: { lr: 0.001 * (trial + 1), bs: 16, opt: "adam" },
    metrics: loss === null ? {} : { loss },
    tags: { sweep_trial: String(trial), sweep_attempt: "0" },
    ...extra,
  };
}

const trials = [
  row(1, "succeeded", 0.4),
  row(0, "succeeded", 0.2),
  row(2, "running", 0.9, { tags: { sweep_trial: "2", sweep_attempt: "0", stopped_early: "true" } }),
  row(3, "failed", null),
];

function renderCard(rows = trials, s = spec) {
  return render(
    <MemoryRouter>
      <SweepCard spec={s} verstr="0.0.1-dev.aaa.bbb" trials={rows}
        boardUrl="/ws/w/app/my_app?q=x" runUrl={(v) => `/run/${v}`} />
    </MemoryRouter>,
  );
}

describe("sweepSpecOf", () => {
  it("reads the spec from run metadata and ignores plain runs", () => {
    expect(sweepSpecOf({ verstr: "v", sweep: spec })).toEqual(spec);
    expect(sweepSpecOf({ verstr: "v" })).toBeNull();
    expect(sweepSpecOf({ verstr: "v", sweep: "nope" })).toBeNull();
  });
});

describe("bestTrial", () => {
  it("follows the metric goal and skips trials without the metric", () => {
    expect(bestTrial(spec, trials)?.name).toBe("sw-t0");
    const max = { ...spec, metric: { name: "loss", goal: "max" as const } };
    expect(bestTrial(max, trials)?.name).toBe("sw-t2");
    expect(bestTrial(spec, [row(0, "running", null)])).toBeNull();
  });
});

describe("SweepCard", () => {
  it("summarizes the spec", () => {
    renderCard();
    const head = screen.getByTestId("sweep-spec");
    expect(head.textContent).toContain("random");
    expect(head.textContent).toContain("loss");
    expect(head.textContent).toContain("min");
    expect(head.textContent).toContain("run cap 20");
    expect(head.textContent).toContain("median");
    expect(head.textContent).toContain("lr");
    expect(head.textContent).toContain("log_uniform");
    expect(head.textContent).toContain("16, 32");
  });

  it("lists trials in trial order with params and the target metric", () => {
    renderCard();
    const rows = screen.getAllByTestId("sweep-trial");
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["0", "1", "2", "3"]);
    expect(rows[1].textContent).toContain("0.4");
    expect(rows[1].textContent).toContain("0.002");
    expect(within(rows[0]).getByRole("link").getAttribute("href")).toBe(`/run/${trials[1].verstr}`);
  });

  it("highlights the best trial", () => {
    renderCard();
    const rows = screen.getAllByTestId("sweep-trial");
    expect(rows[0].className).toContain("best");
    expect(rows[1].className).not.toContain("best");
    expect(screen.getByTestId("sweep-best").textContent).toContain("sw-t0");
    expect(screen.getByTestId("sweep-best").textContent).toContain("0.2");
  });

  it("marks early-stopped trials", () => {
    renderCard();
    expect(screen.getAllByTestId("sweep-trial")[2].textContent).toContain("stopped early");
  });

  it("links to the leaderboard filtered to the sweep", () => {
    renderCard();
    const link = screen.getByRole("link", { name: /leaderboard/i });
    expect(link.getAttribute("href")).toBe("/ws/w/app/my_app?q=x");
  });

  it("says so when no trial ran yet", () => {
    renderCard([]);
    expect(screen.getByText(/no trials yet/i)).toBeInTheDocument();
  });
});
