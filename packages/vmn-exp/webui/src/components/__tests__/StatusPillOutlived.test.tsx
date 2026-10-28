/** Plan 28 T2b: a run still running under an ended outer run (`settled =
 *  "outlived"`) says so on its pill, on the run page and on the board. */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import StatusPill from "../StatusPill";
import RunHead from "../../pages/RunHead";
import type { RunStatus } from "../../types";
import type { RunSummary } from "../../pages/runSummary";
import type { AppStatus } from "../../shell/contracts";
import AttentionStrip from "../AttentionStrip";

const pill = () => document.querySelector(".status-pill") as HTMLElement;

describe("an outlived run's pill", () => {
  it("reads running · outlived, its label why", () => {
    render(<StatusPill status="running" settled="outlived" />);
    expect(pill().className).toBe("status-pill running");
    expect(pill().textContent).toContain("running · outlived");
    expect(pill().getAttribute("title")).toBe("running · outlived its outer run");
    expect(pill().getAttribute("aria-label")).toBe("running · outlived its outer run");
  });

  it("keeps the elapsed time in the label", () => {
    render(<StatusPill status="running" durationSec={120} settled="outlived" />);
    expect(pill().getAttribute("title")).toBe("running for 2m · outlived its outer run");
  });

  it("says nothing of it for another status or settlement", () => {
    const { unmount } = render(<StatusPill status="stuck" settled="lost" />);
    expect(pill().textContent).not.toContain("outlived");
    unmount();
    render(<StatusPill status="running" settled={null} />);
    expect(pill().textContent).toBe("running");
  });
});

const summary = (status: Partial<RunStatus>): RunSummary => ({
  verstr: "0.0.1-dev.k", name: null, tags: {}, branch: null, idx: 2, baseVersion: null, note: null,
  status: status as RunStatus, metrics: {}, params: null,
});

describe("the run page of an outlived inner run", () => {
  it("shows it on the header's pill", () => {
    render(
      <MemoryRouter>
        <RunHead ws="w" app="a" runUrl={(v) => `/r/${v}`} actions={null} summary={summary({
          kind: "inner", status: "running", settled: "outlived", parent: "0.0.1-dev.o", children: [],
        })} />
      </MemoryRouter>,
    );
    expect(screen.getByTitle("running · outlived its outer run")).toBeInTheDocument();
  });
});

describe("the attention strip's built-in outlived part", () => {
  it("reads after stuck, warns, and lists those runs", () => {
    const status: AppStatus = {
      total: 9, failed_recent: 0, rollup: "running",
      counts: { created: 0, running: 4, stuck: 1, succeeded: 4, failed: 0 },
      attention: [{ key: "outlived", label: "outlived their outer run", level: "warn", count: 2,
                    q: 'settled = "outlived"' }],
    };
    render(<MemoryRouter><AttentionStrip status={status} /></MemoryRouter>);
    expect(screen.getByRole("status")).toHaveTextContent(
      "1 stuck · 2 outlived their outer run · 4 running");
    const link = screen.getByRole("link", { name: "2 outlived their outer run" });
    expect(link).toHaveClass("attention-warn");
    expect(new URLSearchParams(link.getAttribute("href")!.split("?")[1]).get("q"))
      .toBe('settled = "outlived"');
  });
});
