/** The column picker's metric toggles write show=/hide= like params, so a
 *  hide=m: entry always means hidden (saved views and links keep working). */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
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
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const head = () => within(document.querySelector("thead") as HTMLElement);

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" }, lr: { hidden: true } });
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([
    row(1, { metrics: { val_loss: 0.5, train_loss: 1, lr: 0.1 } }),
    row(2, { metrics: { val_loss: 0.4, train_loss: 2, lr: 0.2 } }),
  ]));
});

async function openPicker(path?: string) {
  renderBoard(path);
  await screen.findByText("0.0.1-dev.x");
  await waitFor(() => expect(head().queryByText(/^val_loss/)).not.toBeNull());
  fireEvent.click(screen.getByTitle("Columns"));
}

describe("metric toggles in the column picker", () => {
  it("turn a non-goal metric on with show=", async () => {
    await openPicker();
    fireEvent.click(screen.getByLabelText("train_loss"));
    await waitFor(() => expect(urlParams().getAll("show")).toEqual(["m:train_loss"]));
    expect(urlParams().getAll("hide")).toEqual([]);
    expect(head().getByText(/^train_loss/)).toBeInTheDocument();
  });

  it("turn a shown metric off with hide=", async () => {
    await openPicker("/ws/test/app/my-app?show=m:train_loss");
    fireEvent.click(screen.getByLabelText("train_loss"));
    await waitFor(() => expect(urlParams().getAll("hide")).toEqual(["m:train_loss"]));
    expect(urlParams().getAll("show")).toEqual([]);
    expect(head().queryByText(/^train_loss/)).toBeNull();
  });

  it("turn a schema-hidden metric back off without writing hide= (which still shows it)", async () => {
    await openPicker("/ws/test/app/my-app?show=m:lr");
    fireEvent.click(screen.getByLabelText("lr"));
    await waitFor(() => expect(urlParams().getAll("show")).toEqual([]));
    expect(urlParams().getAll("hide")).toEqual([]);
    expect(head().queryByText(/^lr/)).toBeNull();
  });
});
