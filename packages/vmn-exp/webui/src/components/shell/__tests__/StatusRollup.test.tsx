import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import StatusRollup from "../StatusRollup";
import type { AppStatus } from "../../../shell/contracts";

const BASE = "/ws/w/app/a";
const href = (search: string) => `${BASE}${search}`;

function status(
  counts: Partial<AppStatus["counts"]>, failed_recent = 0,
  rollup: AppStatus["rollup"] = null,
): AppStatus {
  return {
    total: 10,
    counts: { created: 0, running: 0, stuck: 0, succeeded: 0, failed: 0, ...counts },
    failed_recent, rollup,
  };
}

function renderRollup(s: AppStatus | null | undefined, compact?: boolean) {
  return render(
    <MemoryRouter><StatusRollup status={s} href={href} compact={compact} /></MemoryRouter>,
  ).container;
}
const dotOf = (c: HTMLElement) => c.querySelector(".rollup-dot");

describe("StatusRollup", () => {
  it("shows the nonzero parts in order: stuck, failed (24h), running", () => {
    const c = renderRollup(status({ stuck: 2, failed: 5, running: 3 }, 1, "stuck"));
    expect(c.textContent).toBe("2 stuck · 1 failed (24h) · 3 running");
  });

  it("links every part to the leaderboard query behind its number", () => {
    renderRollup(status({ stuck: 2, failed: 5, running: 3 }, 1, "stuck"));
    expect(screen.getByRole("link", { name: "2 stuck" })).toHaveAttribute("href", `${BASE}?status=stuck`);
    expect(screen.getByRole("link", { name: "3 running" })).toHaveAttribute("href", `${BASE}?status=running`);
    const failed = screen.getByRole("link", { name: "1 failed (24h)" });
    expect(failed).toHaveAttribute("href", `${BASE}?status=failed&sort=finished_at&order=desc`);
    expect(failed).toHaveAttribute("title", "failed in the last 24 h, newest first");
  });

  it.each([
    [status({ stuck: 1, running: 2 }, 1, "stuck"), "stuck"],
    [status({ failed: 1, running: 2 }, 1, "failed"), "failed"],
    [status({ running: 2 }, 0, "running"), "running"],
  ])("colours the dot by the rollup (%#)", (s, kind) => {
    const dot = dotOf(renderRollup(s))!;
    expect(dot).toHaveClass(`rollup-${kind}`);
    expect(dot).toHaveAttribute("aria-hidden", "true");
  });

  it("gives an old failure no dot and no part", () => {
    const c = renderRollup(status({ failed: 4, running: 1 }, 0, "running"));
    expect(c.textContent).toBe("1 running");
    expect(dotOf(c)).toHaveClass("rollup-running");
  });

  it("gives no dot when nothing needs attention", () => {
    const c = renderRollup(status({ succeeded: 9, failed: 1 }, 0, null));
    expect(dotOf(c)).toBeNull();
  });

  it.each([null, undefined])("renders nothing for %s", (s) => {
    expect(renderRollup(s).innerHTML).toBe("");
  });

  it("renders nothing when every part is zero", () => {
    expect(renderRollup(status({ succeeded: 3, failed: 2 })).innerHTML).toBe("");
  });

  it("compact shows the dot and the first part, the full text in aria-label", () => {
    const c = renderRollup(status({ stuck: 2, running: 3 }, 1, "stuck"), true);
    expect(dotOf(c)).toHaveClass("rollup-stuck");
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveTextContent("2 stuck");
    expect(links[0]).toHaveAccessibleName("2 stuck · 1 failed (24h) · 3 running");
  });
});
