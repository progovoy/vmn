import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithClient } from "../../test-utils";
import RunHistograms, { HISTOGRAM_KEYS_SHOWN } from "../RunHistograms";
import RunMediaSection from "../../pages/RunMedia";
import { hasMedia, histogramUrl } from "../../util/media";
import type { ExperimentDetail } from "../../types";

function mockHistograms() {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((input: string) => {
    const url = String(input);
    calls.push(url);
    const name = decodeURIComponent(url.split("/histograms/")[1]);
    const body = {
      name, total: 7,
      steps: [{ step: 3, bins: [0, 1, 2], counts: [4, 1] }],
    };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  }));
  return calls;
}

describe("histogramUrl", () => {
  it("encodes each segment of the key", () => {
    expect(histogramUrl("ws", "a/b", "v1", "gradients/fc 1.weight")).toBe(
      "/workspaces/ws/apps/a-b/experiments/v1/histograms/gradients/fc%201.weight",
    );
  });
});

describe("hasMedia", () => {
  it("counts histogram keys known only by their totals", () => {
    expect(hasMedia({ histograms: {}, histograms_total: { h: 3 } })).toBe(true);
  });
});

describe("RunHistograms", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("fetches each key's steps and draws its bars", async () => {
    const calls = mockHistograms();
    const { container } = renderWithClient(
      <RunHistograms ws="ws" app="app" verstr="v1" totals={{ "gradients/w": 7 }} />,
    );
    expect(await screen.findByText("step 3")).toBeInTheDocument();
    expect(screen.getByText("gradients/w")).toBeInTheDocument();
    expect(container.querySelectorAll("rect.hist-bar")).toHaveLength(2);
    expect(calls).toEqual(["/api/v1/workspaces/ws/apps/app/experiments/v1/histograms/gradients/w"]);
  });

  it("draws steps the detail inlined without fetching them", async () => {
    const calls = mockHistograms();
    const inline = { h: [{ step: 5, bins: [0, 1, 2], counts: [1, 1] }] };
    renderWithClient(
      <RunHistograms ws="ws" app="app" verstr="v1" totals={{ h: 1 }} inline={inline} />,
    );
    expect(await screen.findByText("step 5")).toBeInTheDocument();
    expect(calls).toEqual([]);
  });

  it("fetches only the keys shown, more on request", async () => {
    const calls = mockHistograms();
    const totals = Object.fromEntries(
      Array.from({ length: HISTOGRAM_KEYS_SHOWN + 5 }, (_, i) => [`k${i}`, 1]),
    );
    renderWithClient(<RunHistograms ws="ws" app="app" verstr="v1" totals={totals} />);
    await waitFor(() => expect(calls).toHaveLength(HISTOGRAM_KEYS_SHOWN));
    fireEvent.click(screen.getByRole("button", { name: /5 more/i }));
    await waitFor(() => expect(calls).toHaveLength(HISTOGRAM_KEYS_SHOWN + 5));
  });
});

describe("RunMediaSection histograms", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("fetches histograms by name when the detail carries totals only", async () => {
    const calls = mockHistograms();
    const detail = {
      metadata: { verstr: "v1" }, metrics: {}, series: {}, patches: {},
      histograms: {}, histograms_total: { h: 7 },
    } as ExperimentDetail;
    renderWithClient(<RunMediaSection ws="ws" app="app" detail={detail} />);
    expect(await screen.findByText("step 3")).toBeInTheDocument();
    expect(calls[0]).toContain("/experiments/v1/histograms/h");
  });
});
