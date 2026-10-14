/** The run page's header badges an outer run (a server without the outer
 *  run's summary shows it there instead of the outer run's page). */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import RunHead from "../RunHead";
import type { RunStatus } from "../../types";
import type { RunSummary } from "../runSummary";

const summary = (status: Partial<RunStatus>): RunSummary => ({
  verstr: "0.0.1-dev.o", name: "kfold-cv", tags: {}, branch: null, idx: 1, baseVersion: null, note: null,
  status: status as RunStatus, metrics: {}, params: null,
});

const renderHead = (s: RunSummary) => render(
  <MemoryRouter>
    <RunHead ws="w" app="a" summary={s} runUrl={(v) => `/ws/w/app/a/run/${v}`} actions={null} />
  </MemoryRouter>,
);

describe("the run page's header", () => {
  it("badges an outer run with its fleet's run count", () => {
    renderHead(summary({
      kind: "outer", status: "succeeded", tree_status: "succeeded", children: ["x"],
      fleet: { expected: 5, counts: { succeeded: 5 } },
    }));
    expect(screen.getByRole("link", { name: "outer · 5 runs" })).toHaveAttribute("href", "/ws/w/app/a/run/0.0.1-dev.o");
  });

  it("gives a single run none", () => {
    renderHead(summary({ kind: "single", status: "succeeded", children: [] }));
    expect(document.querySelector(".outer-badge")).toBeNull();
  });
});
