/** Plan 20 B6: the fleet table shows `@N name`, status, the params that vary
 *  among the children, the goal metric (best marked) and progress only when
 *  known; its headers sort with the keyboard like the leaderboard's. */
import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Fleet, FleetChild, MetricsSchema } from "../../types";
import { FleetCard } from "../RunSections";
import fleetCss from "../../components/fleetTable.css?raw";

function child(n: number, loss: number | null, extra: Partial<FleetChild> = {}): FleetChild {
  return {
    verstr: `0.0.1-dev.abc.c${n}`, status: "succeeded", progress: null, progress_total: null,
    idx: 10 + n, name: `trial-${n}`, params: { lr: n, bs: 32 },
    metrics: loss === null ? { lr: n, bs: 32 } : { loss, lr: n, bs: 32 },
    last_step: null, ...extra,
  };
}

const fleet = (children: FleetChild[]): Fleet => ({
  expected: children.length, counts: { succeeded: children.length }, children,
});

const children = [child(1, 0.5), child(2, 0.2), child(3, null), child(4, 0.9)];

function renderFleet(f: Fleet = fleet(children), schema: MetricsSchema | null = null) {
  return render(
    <MemoryRouter>
      <FleetCard fleet={f} schema={schema} runUrl={(v) => `/run/${v}`} />
    </MemoryRouter>,
  );
}

const table = () => screen.getByRole("table");
const headers = () => within(table()).getAllByRole("columnheader").map((th) => th.textContent?.trim());
const runOrder = () => within(table()).getAllByRole("link").map((a) => a.textContent);

describe("FleetCard table", () => {
  it("labels children @N name and links them to their run", () => {
    renderFleet();
    const link = screen.getByRole("link", { name: "@11 trial-1" });
    expect(link).toHaveAttribute("href", "/run/0.0.1-dev.abc.c1");
    expect(screen.queryByText("0.0.1-dev.abc.c1")).toBeNull();
  });

  it("shows the params that vary among the children, not the constant ones", () => {
    renderFleet();
    expect(headers()).toContain("lr");
    expect(headers()).not.toContain("bs");
  });

  it("shows the goal metric with the best child marked", () => {
    renderFleet();
    expect(headers().some((h) => h?.startsWith("loss"))).toBe(true);
    const best = within(table()).getByText("0.2");
    expect(best.className).toContain("best");
    expect(within(table()).getByText("0.5").className).not.toContain("best");
  });

  it("hides the progress column when no child's progress is known", () => {
    renderFleet();
    expect(headers()).not.toContain("progress");
    expect(table().textContent).not.toContain("—");
  });

  it("shows progress as last_step / of when known", () => {
    renderFleet(fleet([child(1, 0.5, { last_step: { step: 3, of: 10 } }), child(2, 0.2)]));
    expect(headers()).toContain("progress");
    expect(screen.getByText("3 / 10")).toBeInTheDocument();
  });

  it("sorts by the goal metric best first, then reversed, missing values last", () => {
    renderFleet();
    const head = within(table()).getAllByRole("columnheader").find((th) => th.textContent?.startsWith("loss"))!;
    const button = within(head).getByRole("button");
    expect(head).toHaveAttribute("aria-sort", "none");
    fireEvent.keyDown(button, { key: "Enter" });
    expect(head).toHaveAttribute("aria-sort", "ascending");
    expect(runOrder()).toEqual(["@12 trial-2", "@11 trial-1", "@14 trial-4", "@13 trial-3"]);
    fireEvent.keyDown(button, { key: " " });
    expect(head).toHaveAttribute("aria-sort", "descending");
    expect(runOrder()).toEqual(["@14 trial-4", "@11 trial-1", "@12 trial-2", "@13 trial-3"]);
  });

  it("starts a max-goal metric high first", () => {
    const acc = children.map((c, i) => ({ ...c, metrics: { acc: [0.7, 0.9, 0.8, 0.6][i] } }));
    renderFleet(fleet(acc));
    const head = within(table()).getAllByRole("columnheader").find((th) => th.textContent?.startsWith("acc"))!;
    fireEvent.click(within(head).getByRole("button"));
    expect(head).toHaveAttribute("aria-sort", "descending");
    expect(runOrder()[0]).toBe("@12 trial-2");
  });

  it("does not uppercase identifiers in the header (D3)", () => {
    renderFleet();
    expect(table().closest(".fleet-table")).not.toBeNull();
    const rule = /\.fleet-table th\s*\{([^}]*)\}/.exec(fleetCss)?.[1] ?? "";
    expect(rule).toMatch(/text-transform:\s*none/);
  });
});
