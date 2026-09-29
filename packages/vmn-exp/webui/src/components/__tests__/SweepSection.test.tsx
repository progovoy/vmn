import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { SweepSpec, SweepTrial, SweepView } from "../../apiSweep";
import { SweepCard, sweepSpecOf } from "../SweepSection";

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

function trial(n: number, status: string, value: number | null, extra: Partial<SweepTrial> = {}): SweepTrial {
  const verstr = `0.0.1-dev.aaa.bbb.r${n + 2}`;
  return {
    verstr, name: `sw-t${n}`, trial: n, attempt: 0, status,
    params: { lr: 0.001 * (n + 1), bs: 16, opt: "adam" },
    value, metric_source: `${verstr}.nested`, stopped_early: false, ...extra,
  };
}

const trials = [
  trial(0, "succeeded", 0.2),
  trial(1, "succeeded", 0.4),
  trial(2, "succeeded", 0.9, { stopped_early: true }),
  trial(3, "failed", null),
];

function view(t: SweepTrial[] = trials): SweepView {
  const best = t.find((x) => x.value === 0.2);
  return {
    sweep: "0.0.1-dev.aaa.bbb",
    spec,
    trials: t,
    summary: {
      counts: { succeeded: 3, failed: 1 }, stopped_early: 1, trials: t.length,
      best: best ? { verstr: best.verstr, name: best.name, trial: best.trial, value: 0.2, params: best.params } : null,
    },
  };
}

function renderCard(v: SweepView = view()) {
  return render(
    <MemoryRouter>
      <SweepCard view={v} boardUrl="/ws/w/app/my_app?q=x" runUrl={(r) => `/run/${r}`} />
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

describe("SweepCard", () => {
  it("summarizes the spec", () => {
    renderCard();
    const head = screen.getByTestId("sweep-spec");
    for (const text of ["random", "loss", "min", "run cap 20", "median", "lr", "log_uniform", "16, 32"]) {
      expect(head.textContent).toContain(text);
    }
  });

  it("lists the server's trials with params and the attributed metric", () => {
    renderCard();
    const rows = screen.getAllByTestId("sweep-trial");
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["0", "1", "2", "3"]);
    expect(rows[1].textContent).toContain("0.4");
    expect(rows[1].textContent).toContain("0.002");
    expect(within(rows[0]).getAllByRole("link")[0].getAttribute("href")).toBe(`/run/${trials[0].verstr}`);
  });

  it("links a metric that came from a nested run to that run", () => {
    renderCard();
    const cell = within(screen.getAllByTestId("sweep-trial")[0]).getByTitle(/from/i);
    expect(cell.closest("a")?.getAttribute("href")).toBe(`/run/${trials[0].metric_source}`);
  });

  it("highlights the server's best trial", () => {
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
    renderCard(view([]));
    expect(screen.getByText(/no trials yet/i)).toBeInTheDocument();
  });
});
