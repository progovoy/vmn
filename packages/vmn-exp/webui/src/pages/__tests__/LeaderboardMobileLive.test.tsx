/** Below 640px the caption with the live status and Pause sits after every
 *  card, so the page head carries a compact live status too: text only, out
 *  of the tab order, the caption keeping the control and the live region. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../api";
import { NARROW_QUERY } from "../../hooks/useMediaQuery";
import { dropFakeMedia, fakeMedia } from "../../hooks/__tests__/fakeMedia";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const RUNNING = [row(1, { status: "running" }), row(2, { status: "succeeded" })];
const DONE = [row(1, { status: "succeeded" })];

function serve(rows: ReturnType<typeof row>[]) {
  m.experiments.mockResolvedValue(page(rows));
  m.experimentsPaged.mockResolvedValue({ rows, total: rows.length });
}

async function head() {
  renderBoard();
  await screen.findAllByRole("link", { name: RUNNING[0].verstr });
  return screen.getByRole("heading", { level: 1 }).closest(".page-head") as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  serve(RUNNING);
});
afterEach(dropFakeMedia);

describe("the phone board's live status in the head", () => {
  it("shows live in the head while a run is running, with no control there", async () => {
    fakeMedia([NARROW_QUERY]);
    const h = await head();
    const badge = h.querySelector(".board-live") as HTMLElement;
    expect(badge).toHaveTextContent(/live · updated/);
    expect(badge).toHaveAttribute("aria-hidden", "true");
    expect(badge.querySelector("button, a, [tabindex]")).toBeNull();
    expect(within(h).queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });

  it("follows Pause in the caption", async () => {
    fakeMedia([NARROW_QUERY]);
    const h = await head();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(h.querySelector(".board-live")).toHaveTextContent(/^paused/);
  });

  it("is absent with nothing running", async () => {
    fakeMedia([NARROW_QUERY]);
    serve(DONE);
    expect((await head()).querySelector(".board-live")).toBeNull();
  });

  it("is absent on a wide screen, where the caption is in view", async () => {
    fakeMedia([]);
    expect((await head()).querySelector(".board-live")).toBeNull();
  });
});
