import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusPill from "../StatusPill";
import type { RunState } from "../../types";

const STATES: RunState[] = ["created", "running", "stuck", "succeeded", "failed"];

function pill(): HTMLElement {
  return document.querySelector(".status-pill") as HTMLElement;
}

describe("StatusPill", () => {
  it("renders a pill per status with its own class and label", () => {
    STATES.forEach((s) => {
      const { unmount } = render(<StatusPill status={s} />);
      expect(screen.getByText(s)).toBeInTheDocument();
      expect(pill().className).toBe(`status-pill ${s}`);
      unmount();
    });
  });

  it("distinguishes stuck from running with a warning affordance", () => {
    const { unmount } = render(<StatusPill status="running" durationSec={90} />);
    const running = pill();
    expect(running.className).toContain("running");
    expect(running.textContent).not.toContain("⚠");
    unmount();

    render(<StatusPill status="stuck" staleSec={300} />);
    const stuck = pill();
    expect(stuck.className).toContain("stuck");
    expect(stuck.textContent).toContain("⚠");
  });

  it("gives the running pill a live dot", () => {
    render(<StatusPill status="running" durationSec={5} />);
    expect(pill().querySelector(".dot")).not.toBeNull();
    expect(pill().className).toContain("running");
  });

  it("puts the exit code in the accessible label of a failed run", () => {
    render(<StatusPill status="failed" exitCode={2} durationSec={12} />);
    const label = pill().getAttribute("aria-label") ?? "";
    expect(label).toContain("exit 2");
    expect(pill().getAttribute("title")).toBe(label);
  });

  it("puts the elapsed time in the label of a running run", () => {
    render(<StatusPill status="running" durationSec={120} />);
    expect(pill().getAttribute("aria-label")).toContain("2m");
  });

  it("puts the missing-heartbeat age in the label of a stuck run", () => {
    render(<StatusPill status="stuck" staleSec={300} />);
    expect(pill().getAttribute("aria-label")).toContain("no heartbeat for 5m");
  });

  it("reports the final duration for a succeeded run", () => {
    render(<StatusPill status="succeeded" exitCode={0} durationSec={45} />);
    expect(pill().getAttribute("aria-label")).toContain("45s");
  });

  it("adds the error summary to a failed run's tooltip", () => {
    render(<StatusPill status="failed" exitCode={1} errorSummary="RuntimeError: boom" />);
    expect(pill().title).toBe("failed — exit 1 — RuntimeError: boom");
    expect(pill().getAttribute("aria-label")).toBe(pill().title);
  });

  it("keeps the plain label of a failed run without a summary", () => {
    render(<StatusPill status="failed" exitCode={1} errorSummary={null} />);
    expect(pill().title).toBe("failed — exit 1");
  });

  it("marks a released waiting run, and when it was handed back (plan 28 API2)", () => {
    const at = new Date(Date.now() - 180_000).toISOString();
    render(<StatusPill status="created" releasedAt={at} />);
    expect(pill().textContent).toContain("created · released");
    expect(pill().getAttribute("title")).toBe("waiting — released 3m ago");
  });

  it("says nothing of an old release once the run is running again", () => {
    render(<StatusPill status="running" releasedAt="2026-01-01T00:00:00Z" />);
    expect(pill().textContent).not.toContain("released");
  });
});
