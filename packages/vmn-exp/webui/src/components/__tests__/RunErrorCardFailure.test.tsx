import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import RunErrorCard, { type FailureContext } from "../RunErrorCard";
import type { RunState, RunStatus } from "../../types";

function status(state: RunState, extra: Partial<RunStatus> = {}): RunStatus {
  return {
    status: state, exit_code: null, started_at: null, finished_at: null, heartbeat: null,
    duration_sec: null, pid: null, host: null, command: null, stale_sec: null, parent: null,
    children: [], kind: "single", depth: 0, tree_status: null, last_metric_at: null, ...extra,
  };
}

const RUN_URL = "/ws/test/app/my-app/run/0.0.2-dev.bad";
const card = () => document.querySelector(".run-error-card") as HTMLElement;

function renderCard(context: FailureContext, extra: { hasOutputLog?: boolean; st?: RunStatus } = {}) {
  return render(
    <MemoryRouter initialEntries={[RUN_URL]}>
      <RunErrorCard status={extra.st ?? status("failed", { exit_code: 1 })}
        hasOutputLog={extra.hasOutputLog} context={context} runPath={RUN_URL} />
    </MemoryRouter>,
  );
}

const lines = (n: number) => Array.from({ length: n }, (_, i) => `line ${i + 1}`);

describe("RunErrorCard failure context", () => {
  it("shows the output tail in a mono block, keeping the last 40 lines", () => {
    renderCard({ output_tail: { lines: lines(45), truncated: true } }, { hasOutputLog: true });
    const pre = card().querySelector("pre.run-error-tail") as HTMLElement;
    expect(pre).not.toBeNull();
    expect(pre.className).toContain("mono");
    const shown = pre.textContent!.split("\n");
    expect(shown).toHaveLength(40);
    expect(shown[0]).toBe("line 6");
    expect(shown[39]).toBe("line 45");
    const open = screen.getByRole("link", { name: "open full output" });
    expect(open).toHaveAttribute("href", "#run-output");
  });

  it("scrolls the output tail to its end, where the run died", () => {
    const desc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get: () => 700 });
    try {
      renderCard({ output_tail: { lines: lines(40), truncated: false } });
      expect((card().querySelector("pre.run-error-tail") as HTMLElement).scrollTop).toBe(700);
    } finally {
      if (desc) Object.defineProperty(HTMLElement.prototype, "scrollHeight", desc);
      else delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollHeight;
    }
  });

  it("prefers the output log's tail over the error's captured tail", () => {
    renderCard({ output_tail: { lines: ["from log"], truncated: false } }, {
      st: status("failed", { error: { message: "Killed", output_tail: "from error" } }),
    });
    const pres = card().querySelectorAll("pre.run-error-tail");
    expect(pres).toHaveLength(1);
    expect(pres[0].textContent).toBe("from log");
  });

  it("has no output block and no full-output link without a tail", () => {
    renderCard({ output_tail: null }, { hasOutputLog: true });
    expect(card().querySelector("pre.run-error-tail")).toBeNull();
    expect(screen.queryByRole("link", { name: "open full output" })).toBeNull();
  });

  it("omits the full-output link when the output card is not on the page", () => {
    renderCard({ output_tail: { lines: ["x"], truncated: false } });
    expect(card().querySelector("pre.run-error-tail")).not.toBeNull();
    expect(screen.queryByRole("link", { name: "open full output" })).toBeNull();
  });

  it("says where the run stopped, with its planned length when known", () => {
    const { unmount } = renderCard({ last_step: { step: 38, of: 86 } });
    expect(card().querySelector(".run-error-step")?.textContent).toBe("stopped at step 38 of 86");
    unmount();
    renderCard({ last_step: { step: 7, of: null } });
    expect(card().querySelector(".run-error-step")?.textContent).toBe("stopped at step 7");
  });

  it("has no step line without a last step", () => {
    renderCard({ last_step: null });
    expect(card().querySelector(".run-error-step")).toBeNull();
  });

  it("links the last good run to the Changes card with it as baseline", () => {
    renderCard({ last_good: { verstr: "0.0.2-dev.good", idx: 41, name: "hist-000488" } });
    const since = card().querySelector(".run-error-since") as HTMLElement;
    expect(since.textContent).toContain("Since it last worked: @41 hist-000488");
    const link = screen.getByRole("link", { name: /changes/i });
    expect(link).toHaveAttribute("href", `${RUN_URL}?baseline=0.0.2-dev.good#changes`);
  });

  it("names a last good run without an index by its verstr", () => {
    renderCard({ last_good: { verstr: "0.0.2-dev.good", idx: null, name: null } });
    expect(card().querySelector(".run-error-since")?.textContent).toContain("0.0.2-dev.good");
  });

  it("has no since-it-worked line without a last good run", () => {
    renderCard({ last_good: null });
    expect(card().querySelector(".run-error-since")).toBeNull();
  });
});
