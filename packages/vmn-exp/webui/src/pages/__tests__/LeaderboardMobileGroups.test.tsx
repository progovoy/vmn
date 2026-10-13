/// <reference types="vite/client" />
/** Plan 22 W4 (G9): below 640px a grouped board heads each group's cards
 *  with a sticky section label — the group's name, its status count and its
 *  aggregate on the primary metric — and nothing pushes the page sideways. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(),
    experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    config: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));

import { api } from "../../api";
import { NONE_GROUP, type RunGroup } from "../../apiGroups";
import { NARROW_QUERY } from "../../hooks/useMediaQuery";
import { dropFakeMedia, fakeMedia } from "../../hooks/__tests__/fakeMedia";
import groupCss from "../leaderboardCardGroup.css?raw";
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const counts = (extra = {}) => ({ total: 3, running: 1, waiting: 0, done: 1, failed: 1, stuck: 0, ...extra });
const agg = (mean: number, extra = {}) => ({ mean, best: mean / 2, median: mean, min: mean / 2, max: mean * 2, n: 3, ...extra });

const OUTER = row(1, { kind: "outer", name: "sweep", children: [v(2), v(3)], tree_status: "failed", metrics: { loss: 0.9 } });
const INNER = [row(2, { kind: "inner", parent: v(1), depth: 1, metrics: { loss: 0.2 } }),
  row(3, { kind: "inner", parent: v(1), depth: 1, status: "failed", metrics: { loss: 0.4 } })];
const LONE = row(4, { metrics: { loss: 0.5 } });

const sweepGroup = (extra: Partial<RunGroup> = {}): RunGroup => ({
  key: v(1), label: v(1),
  target: { verstr: v(1), idx: 1, name: "sweep", status: "succeeded", tree_status: "failed", metrics: { loss: 0.91 } },
  counts: counts(), aggregates: { loss: agg(0.3), acc: agg(0.8, { best: null }) }, rows: INNER, rows_total: 2,
  ...extra,
});
const noParent = (): RunGroup => ({
  key: NONE_GROUP, label: "(no parent run)", target: null, counts: counts({ total: 2, running: 0, failed: 0 }),
  aggregates: {}, rows: [OUTER, LONE], rows_total: 2,
});
const grouped = (groups: RunGroup[]) => ({ groups, total_groups: groups.length, total_rows: 4 });

const sections = () => [...document.querySelectorAll(".lb-mgroup")] as HTMLElement[];
const section = (text: string) =>
  sections().find((s) => s.querySelector(".lb-mgroup-head")?.textContent?.includes(text)) as HTMLElement;
const head = (text: string) => section(text).querySelector(".lb-mgroup-head") as HTMLElement;
const cardNames = (s: HTMLElement) => [...s.querySelectorAll(".lb-mcard .lb-mcard-name")].map((a) => a.textContent);
const shown = async () => {
  renderBoard();
  await screen.findByRole("list", { name: "experiments" });
  await waitFor(() => expect(sections()).toHaveLength(2));
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  fakeMedia([NARROW_QUERY]);
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.config.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiment.mockResolvedValue({ metadata: { verstr: "x" }, metrics: {}, series: {}, patches: {} });
  m.experiments.mockResolvedValue(page([OUTER, ...INNER, LONE]));
  m.facets.mockResolvedValue({
    branches: ["main"], metric_keys: ["loss", "acc"], param_keys: [], tag_keys: [], param_values: {}, parented: 2, total: 4,
  });
  m.experimentGroups.mockResolvedValue(grouped([sweepGroup(), noParent()]));
});
afterEach(dropFakeMedia);

describe("a grouped board below 640px", () => {
  it("heads each group's cards with its section label, in the server's order", async () => {
    await shown();
    expect(screen.queryByRole("grid", { name: "experiments" })).toBeNull();
    expect(sections().map((s) => s.querySelector(".lb-mgroup-label")?.textContent)).toEqual(["sweep", "(no parent run)"]);
    expect(cardNames(section("sweep"))).toEqual([v(2), v(3)]);
    expect(cardNames(section("(no parent run)"))).toEqual(["sweep", v(4)]);
    // The label comes before its cards.
    const s = section("sweep");
    expect(s.firstElementChild).toBe(head("sweep"));
  });

  it("names a link group by its target run, linked", async () => {
    await shown();
    expect(within(head("sweep")).getByRole("link", { name: "sweep" }))
      .toHaveAttribute("href", `/ws/test/app/my-app/run/${v(1)}`);
    expect(within(head("(no parent run)")).queryByRole("link")).toBeNull();
  });

  it("shows the status count in colour, and in words for a screen reader", async () => {
    await shown();
    const h = head("sweep");
    expect(h.querySelector(".group-counts")?.textContent).toBe("3 runs · 1 running · 1 failed");
    expect(h.querySelector(".group-counts .tone-failed")?.textContent).toBe("1 failed");
    expect(within(h).getByText("Group sweep: 3 runs, 1 running, 1 failed")).toHaveClass("sr-only");
  });

  it("says `2 of 5` when the filters leave part of the group (plan 22 F1)", async () => {
    m.experimentGroups.mockResolvedValue(grouped([sweepGroup({ counts: counts({ total: 2 }), rows_unfiltered: 5 }), noParent()]));
    await shown();
    const h = head("sweep");
    expect(h.querySelector(".group-counts")?.textContent).toBe("2 of 5 runs · 1 running · 1 failed");
    expect(within(h).getByText("Group sweep: 2 of 5 runs, 1 running, 1 failed")).toHaveClass("sr-only");
  });

  it("selects a group's loaded cards from its section label's checkbox (plan 22 F8)", async () => {
    await shown();
    const box = within(head("sweep")).getByRole("checkbox", { name: "Select group sweep" }) as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    await waitFor(() => expect(urlParams().getAll("sel").sort()).toEqual([v(2), v(3)]));
    expect(box.checked).toBe(true);
    // Not the header's target run.
    expect(urlParams().getAll("sel")).not.toContain(v(1));
    fireEvent.click(box);
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([]));
  });

  it("shows the section checkbox indeterminate when only some of its cards are selected", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(2)}`);
    await waitFor(() => expect(sections()).toHaveLength(2));
    const box = within(head("sweep")).getByRole("checkbox", { name: "Select group sweep" }) as HTMLInputElement;
    await waitFor(() => expect(box.indeterminate).toBe(true));
    expect(box.checked).toBe(false);
  });

  it("has no section checkbox for a group with no loaded cards", async () => {
    m.experimentGroups.mockResolvedValue(grouped([sweepGroup({ rows: [], rows_total: 2 }), noParent()]));
    await shown();
    expect(within(head("sweep")).queryByRole("checkbox")).toBeNull();
    expect(within(head("(no parent run)")).getByRole("checkbox", { name: "Select group (no parent run)" })).toBeInTheDocument();
  });

  it("shows the group's aggregate on the primary metric and names it", async () => {
    await shown();
    const a = head("sweep").querySelector(".lb-mgroup-agg") as HTMLElement;
    expect(a.querySelector(".lb-mgroup-value")?.textContent).toBe("0.3");
    expect(a).toHaveTextContent("loss");
    expect(a).toHaveTextContent("mean");
    expect(a).toHaveAttribute("title", "mean of 3");
    // A group with no value on the metric shows none.
    expect(head("(no parent run)").querySelector(".lb-mgroup-agg")).toBeNull();
  });

  it("shows the chosen aggregate, and the one of the metric the board is sorted by", async () => {
    renderBoard("/ws/test/app/my-app?agg=best");
    await waitFor(() => expect(sections()).toHaveLength(2));
    expect(head("sweep").querySelector(".lb-mgroup-value")?.textContent).toBe("0.15");
    expect(head("sweep").querySelector(".lb-mgroup-agg")).toHaveAttribute("title", "best of 3");
  });

  it("folds a group shut and open again from its label, remembering it in collapse=", async () => {
    await shown();
    expect(within(head("(no parent run)")).queryByRole("button", { name: /group/i })).toBeNull();
    const fold = within(head("sweep")).getByRole("button", { name: "Collapse group sweep" });
    expect(fold).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(fold);
    await waitFor(() => expect(screen.queryByRole("link", { name: v(2) })).toBeNull());
    expect(urlParams().getAll("collapse")).toEqual([v(1)]);
    // The label stays, so the group can be opened again.
    fireEvent.click(within(head("sweep")).getByRole("button", { name: "Expand group sweep" }));
    expect(await screen.findByRole("link", { name: v(2) })).toBeInTheDocument();
  });

  it("loads the rest of a group from its +N more button", async () => {
    m.experimentGroups.mockResolvedValue(grouped([sweepGroup({ rows: [INNER[0]], rows_total: 2 })]));
    m.experimentGroupRows.mockResolvedValue({ ...sweepGroup(), rows: [INNER[1]] });
    renderBoard();
    fireEvent.click(await screen.findByRole("button", { name: "+1 more" }));
    expect(await screen.findByRole("link", { name: v(3) })).toBeInTheDocument();
    expect(m.experimentGroupRows.mock.calls[0][2]).toBe(v(1));
    expect(cardNames(section("sweep"))).toEqual([v(2), v(3)]);
  });

  it("still selects every card on screen", async () => {
    await shown();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all visible runs" }));
    await waitFor(() => expect(urlParams().getAll("sel")).toHaveLength(4));
  });
});

/** Declarations of the rule whose selector list names *selector*. */
function decls(css: string, selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const [, sel, body] of plain.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!sel.split(",").map((s) => s.trim()).includes(selector)) continue;
    for (const d of body.split(";")) {
      const i = d.indexOf(":");
      if (i > 0) out[d.slice(0, i).trim()] = d.slice(i + 1).trim();
    }
  }
  return out;
}

describe("the 390px section label (read from its stylesheet)", () => {
  it("sticks to the top of the scrolling board over the cards that pass under it", () => {
    const d = decls(groupCss, ".lb-mgroup-head");
    expect(d.position).toBe("sticky");
    expect(d.top).toBe("0");
    expect(d["z-index"]).toBeDefined();
    expect(d.background).toMatch(/var\(--/);
  });

  it("truncates a long name instead of widening the page", () => {
    const d = decls(groupCss, ".lb-mgroup-label");
    expect(d.overflow).toBe("hidden");
    expect(d["text-overflow"]).toBe("ellipsis");
    expect(d["white-space"]).toBe("nowrap");
    expect(decls(groupCss, ".lb-mgroup-name")["min-width"]).toBe("0");
    expect(decls(groupCss, ".lb-mgroup")["min-width"]).toBe("0");
  });

  it("wraps the count line instead of cutting it (plan 22 F2), still never wider than the screen", () => {
    const d = decls(groupCss, ".lb-mgroup-counts");
    expect(d["white-space"] ?? "normal").not.toBe("nowrap");
    expect(d["text-overflow"]).toBeUndefined();
    expect(d["overflow-wrap"]).toBe("anywhere");
  });
});
