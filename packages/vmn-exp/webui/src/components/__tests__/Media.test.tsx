import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderWithClient } from "../../test-utils";
import MediaImages from "../MediaImages";
import MediaHistograms from "../MediaHistograms";
import MediaTable from "../MediaTable";
import RunMediaSection from "../../pages/RunMedia";
import type { ExperimentDetail, TablePage } from "../../types";

const url = (path: string) => `/files/${path}`;

describe("MediaImages", () => {
  const media = {
    samples: [
      { step: 0, path: "media/samples/0.png", caption: "first" },
      { step: 4, path: "media/samples/4.png", caption: "last" },
    ],
  };

  it("shows each key's newest step, with its caption", () => {
    render(<MediaImages media={media} url={url} />);
    expect(screen.getByText("samples")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("src", "/files/media/samples/4.png");
    expect(screen.getByText("last")).toBeInTheDocument();
    expect(screen.getByText("step 4")).toBeInTheDocument();
  });

  it("a step slider moves through the logged steps", () => {
    render(<MediaImages media={media} url={url} />);
    fireEvent.change(screen.getByLabelText("step of samples"), { target: { value: "0" } });
    expect(screen.getByRole("img")).toHaveAttribute("src", "/files/media/samples/0.png");
    expect(screen.getByText("first")).toBeInTheDocument();
  });
});

describe("MediaHistograms", () => {
  const histograms = {
    weights: [
      { step: 0, bins: [0, 1, 2, 3], counts: [1, 2, 3] },
      { step: 9, bins: [0, 2, 4, 6], counts: [5, 0, 1] },
    ],
  };

  it("draws one bar per bin for the chosen step", () => {
    const { container } = render(
      <MediaHistograms histograms={histograms} totals={{ weights: 2 }} />,
    );
    expect(container.querySelectorAll("rect.hist-bar")).toHaveLength(3);
    expect(screen.getByText("step 9")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("step of weights"), { target: { value: "0" } });
    expect(screen.getByText("step 0")).toBeInTheDocument();
  });

  it("an over-time view stacks every step", () => {
    const { container } = render(
      <MediaHistograms histograms={histograms} totals={{ weights: 30 }} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /over time/i }));
    expect(container.querySelectorAll("g.hist-row")).toHaveLength(2);
    expect(screen.getByText(/2 of 30 steps/)).toBeInTheDocument();
  });
});

function page(rows: unknown[][], total: number, offset = 0): TablePage {
  return {
    columns: [{ name: "n", type: "number" }, { name: "label", type: "string" }],
    rows, total, offset, truncated: false,
  };
}

function mockFetch(pages: TablePage[]) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((input: string) => {
    calls.push(String(input));
    const body = pages[Math.min(calls.length - 1, pages.length - 1)];
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  }));
  return calls;
}

describe("MediaTable", () => {
  afterEach(() => vi.unstubAllGlobals());
  const tables = { preds: [{ step: 0, path: "tables/preds/0.json", rows: 60, columns: ["n", "label"] }] };

  it("shows a page of rows and pages forward", async () => {
    const calls = mockFetch([page([[1, "a"]], 60), page([[51, "z"]], 60, 50)]);
    renderWithClient(<MediaTable ws="ws" app="app" verstr="v1" tables={tables} />);
    expect(await screen.findByText("a")).toBeInTheDocument();
    expect(calls[0]).toContain("/experiments/v1/table/tables/preds/0.json?offset=0&limit=50");
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(await screen.findByText("z")).toBeInTheDocument();
    expect(calls[1]).toContain("offset=50");
  });

  it("sorts server-side by a clicked column, toggling the order", async () => {
    const calls = mockFetch([page([[1, "a"]], 1)]);
    renderWithClient(<MediaTable ws="ws" app="app" verstr="v1" tables={tables} />);
    await screen.findByText("a");
    fireEvent.click(screen.getByRole("button", { name: "n" }));
    await waitFor(() => expect(calls.some((c) => c.includes("sort=n&order=asc"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: /n ▲/ }));
    await waitFor(() => expect(calls.some((c) => c.includes("sort=n&order=desc"))).toBe(true));
  });
});

describe("RunMediaSection", () => {
  const base = { metadata: { verstr: "v1" }, metrics: {}, series: {}, patches: {} } as ExperimentDetail;

  it("renders nothing for a run without media", () => {
    const { container } = render(<RunMediaSection ws="ws" app="app" detail={base} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a Media card when anything was logged", () => {
    render(
      <RunMediaSection ws="ws" app="app" detail={{
        ...base, media: { s: [{ step: 0, path: "outputs/media/s/0.png" }] },
      }} />,
    );
    expect(screen.getByText("media")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute(
      "src", "/api/v1/workspaces/ws/apps/app/experiments/v1/outputs/media/s/0.png",
    );
  });
});
