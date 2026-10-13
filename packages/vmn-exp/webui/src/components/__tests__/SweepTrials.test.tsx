/** Plan 20 B6: a sweep's trials table is the fleet table (`@N name`, varying
 *  params, the sweep metric, sortable) and the sweep gets a
 *  parallel-coordinates chart over its trials. */
import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { SweepTrial, SweepView } from "../../apiSweep";
import { SweepCard } from "../SweepSection";

function trial(n: number, value: number | null): SweepTrial {
  const verstr = `0.0.1-dev.aaa.bbb.t${n}`;
  return {
    verstr, name: `sw-t${n}`, trial: n, attempt: 0, status: "succeeded",
    params: { lr: 0.001 * (n + 1), opt: "adam" }, value, metric_source: verstr, stopped_early: false,
  };
}

const trials = [trial(0, 0.4), trial(1, 0.2), trial(2, null)];

const view: SweepView = {
  sweep: "0.0.1-dev.aaa.bbb",
  spec: {
    method: "grid", metric: { name: "loss", goal: "min" },
    parameters: { lr: { values: [0.001, 0.002, 0.003] }, opt: { value: "adam" } },
  },
  trials,
  summary: {
    counts: { succeeded: 3 }, stopped_early: 0, trials: 3,
    best: { verstr: trials[1].verstr, name: "sw-t1", trial: 1, value: 0.2, params: trials[1].params },
  },
};

const idx = { [trials[0].verstr]: 5, [trials[1].verstr]: 6, [trials[2].verstr]: 7 };

function renderCard() {
  return render(
    <MemoryRouter>
      <SweepCard view={view} idxOf={(v) => idx[v] ?? null} boardUrl="/b" runUrl={(r) => `/run/${r}`} />
    </MemoryRouter>,
  );
}

const trialTable = () => screen.getAllByRole("table")[0];

describe("SweepCard trials", () => {
  it("labels trials @N name and never prints their verstrs", () => {
    renderCard();
    expect(within(trialTable()).getByRole("link", { name: "@6 sw-t1" })).toBeInTheDocument();
    for (const t of trials) expect(document.body.textContent).not.toContain(t.verstr);
  });

  it("drops a parameter that is constant across the trials", () => {
    renderCard();
    const heads = within(trialTable()).getAllByRole("columnheader").map((th) => th.textContent);
    expect(heads).toContain("lr");
    expect(heads).not.toContain("opt");
  });

  it("sorts trials by the sweep metric toward its goal", () => {
    renderCard();
    const head = within(trialTable()).getAllByRole("columnheader").find((th) => th.textContent?.startsWith("loss"))!;
    fireEvent.keyDown(within(head).getByRole("button"), { key: "Enter" });
    const order = screen.getAllByTestId("sweep-trial").map((r) => within(r).getAllByRole("cell")[0].textContent);
    expect(order).toEqual(["1", "0", "2"]);
  });

  it("draws the trials as parallel coordinates over the metric and the varying params", async () => {
    renderCard();
    const axes = await screen.findAllByTestId("axis");
    expect(axes).toHaveLength(2);
    expect(screen.getAllByTestId("row-line")).toHaveLength(3);
  });
});
