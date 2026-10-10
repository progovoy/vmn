import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import RunErrorCard from "../RunErrorCard";
import type { RunError, RunState, RunStatus } from "../../types";

function status(state: RunState, extra: Partial<RunStatus> = {}): RunStatus {
  return {
    status: state, exit_code: null, started_at: null, finished_at: null, heartbeat: null,
    duration_sec: null, pid: null, host: null, command: null, stale_sec: null, parent: null,
    children: [], kind: "single", depth: 0, tree_status: null, last_metric_at: null, ...extra,
  };
}

const TRACEBACK = [
  "Traceback (most recent call last):",
  '  File "train.py", line 10, in <module>',
  "    main()",
  "RuntimeError: dataloader worker died",
  "",
].join("\n");

const ERR: RunError = {
  type: "RuntimeError", message: "dataloader worker died\nsecond line", traceback: TRACEBACK,
  source: "exception", output_tail: "epoch 3 loss=0.2",
};

const card = () => document.querySelector(".run-error-card") as HTMLElement | null;

afterEach(() => vi.unstubAllGlobals());

describe("RunErrorCard", () => {
  it("renders nothing for succeeded, running and stuck runs without an error", () => {
    for (const s of ["succeeded", "running", "stuck", "created"] as RunState[]) {
      const { unmount } = render(<RunErrorCard status={status(s, { exit_code: s === "succeeded" ? 0 : null })} />);
      expect(card()).toBeNull();
      unmount();
    }
  });

  it("shows the headline, meta line and traceback of a recorded exception", () => {
    render(<RunErrorCard status={status("failed", { exit_code: 137, signal: "SIGKILL", error: ERR })} />);
    expect(card()).not.toBeNull();
    expect(screen.getByText("error")).toBeInTheDocument();
    const headline = card()!.querySelector(".run-error-headline") as HTMLElement;
    expect(headline.textContent).toBe("RuntimeError: dataloader worker died\nsecond line");
    const meta = card()!.querySelector(".run-error-meta") as HTMLElement;
    expect(meta.textContent).toContain("exit code 137");
    expect(meta.textContent).toContain("killed by SIGKILL");
    const pre = card()!.querySelector("pre.run-error-traceback") as HTMLElement;
    expect(pre.textContent).toContain('File "train.py", line 10');
    expect(pre.querySelector(".run-error-final")?.textContent).toBe("RuntimeError: dataloader worker died");
  });

  it("shows the card for an error even when the run is not marked failed", () => {
    render(<RunErrorCard status={status("succeeded", { error: { type: "ValueError", message: "bad" } })} />);
    expect(card()!.querySelector(".run-error-headline")?.textContent).toBe("ValueError: bad");
  });

  it("scrolls the traceback to the bottom so the raising frame is visible", () => {
    const desc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get: () => 900 });
    try {
      render(<RunErrorCard status={status("failed", { error: ERR })} />);
      const pre = card()!.querySelector("pre.run-error-traceback") as HTMLElement;
      expect(pre.scrollTop).toBe(900);
    } finally {
      if (desc) Object.defineProperty(HTMLElement.prototype, "scrollHeight", desc);
      else delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollHeight;
    }
  });

  it("copies the traceback", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<RunErrorCard status={status("failed", { error: ERR })} />);
    fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(TRACEBACK));
    expect(await screen.findByText("copied")).toBeInTheDocument();
  });

  it("keeps the last output collapsed under a traceback, open without one", () => {
    const { unmount } = render(<RunErrorCard status={status("failed", { error: ERR })} />);
    let details = card()!.querySelector("details.run-error-output") as HTMLDetailsElement;
    expect(details.querySelector("summary")?.textContent).toBe("last output");
    expect(details.textContent).toContain("epoch 3 loss=0.2");
    expect(details.open).toBe(false);
    unmount();

    render(<RunErrorCard status={status("failed", {
      error: { source: "output", message: "Killed", output_tail: "oom" },
    })} />);
    details = card()!.querySelector("details.run-error-output") as HTMLDetailsElement;
    expect(details.open).toBe(true);
    expect(card()!.querySelector("pre.run-error-traceback")).toBeNull();
    expect(card()!.querySelector(".run-error-headline")?.textContent).toBe("Killed");
  });

  it("says no exception was recorded for a failed run without one", () => {
    render(<RunErrorCard status={status("failed", { exit_code: 2 })} />);
    expect(card()!.textContent).toContain("No exception was recorded — exit code 2");
    expect(card()!.querySelector('a[href="#run-output"]')).toBeNull();
  });

  it("points at the output card when the run kept its output", () => {
    render(<RunErrorCard status={status("failed", { exit_code: 2 })} hasOutputLog />);
    expect(card()!.querySelector('a[href="#run-output"]')).not.toBeNull();
  });

  it("falls back to error_summary when only the row summary is known", () => {
    render(<RunErrorCard status={status("failed", { exit_code: 1, error_summary: "KeyError: 'x'" })} />);
    expect(card()!.querySelector(".run-error-headline")?.textContent).toBe("KeyError: 'x'");
    expect(card()!.textContent).not.toContain("No exception was recorded");
  });
});
