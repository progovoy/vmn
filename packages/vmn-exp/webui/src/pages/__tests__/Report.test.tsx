import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiReports", async (orig) => ({
  ...(await orig<typeof import("../../apiReports")>()),
  apiReports: { getReport: vi.fn(), getRevision: vi.fn(), listComments: vi.fn(), publish: vi.fn() },
}));
vi.mock("../../reports/Panel", () => ({
  default: ({ spec, published }: { spec: { id: string }; published?: { rev: number } }) => (
    <div>panel {spec.id}{published ? ` frozen ${published.rev}` : ""}</div>
  ),
}));

import { apiReports } from "../../apiReports";
import Report from "../Report";

const m = apiReports as unknown as Record<string, ReturnType<typeof vi.fn>>;

const BODIES: Record<number, string> = {
  1: "# Published body\n\n```vmn-panel\nid: loss\ntype: curves\n```\n",
  2: "# Draft body\nnew line\n",
};

function report(extra: Record<string, unknown> = {}) {
  return {
    rid: "r1", title: "LR sweep", rev: 2, body: BODIES[2], author: "bob", published_rev: 1,
    published_at: "2026-01-05T00:00:00Z", archived: false, pinned: false,
    revisions: [
      { rev: 1, author: "ann", created_at: "2026-01-01T00:00:00Z", message: "first" },
      { rev: 2, author: "bob", created_at: "2026-01-06T00:00:00Z", message: "more" },
    ],
    ...extra,
  };
}

function renderReport(url = "/ws/w/reports/r1") {
  return renderWithClient(
    <MemoryRouter initialEntries={[url]}>
      <Routes><Route path="/ws/:ws/reports/:rid" element={<Report />} /></Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.getReport.mockResolvedValue(report());
  m.getRevision.mockImplementation((_ws: string, _rid: string, n: number) =>
    Promise.resolve({ rev: n, body: BODIES[n], author: "x" }));
  m.listComments.mockResolvedValue({ comments: [] });
});

describe("Report page", () => {
  it("opens the published revision with a live toggle", async () => {
    renderReport();
    expect(await screen.findByRole("heading", { name: "Published body" })).toBeTruthy();
    expect(screen.getByText(/published 2026-01-05/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Edit" })).toBeNull();
    expect(document.getElementById("p-loss")?.textContent).toBe("panel loss frozen 1");
    fireEvent.click(screen.getByRole("button", { name: /view live/ }));
    expect(await screen.findByRole("heading", { name: "Draft body" })).toBeTruthy();
  });

  it("opens the draft for editors and with ?live=1", async () => {
    m.getReport.mockResolvedValue(report({ can_edit: true }));
    renderReport();
    expect(await screen.findByRole("heading", { name: "Draft body" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Edit" }).getAttribute("href")).toBe("/ws/w/reports/r1/edit");
  });

  it("opens live with ?live=1 and a given revision with ?rev=N", async () => {
    renderReport("/ws/w/reports/r1?live=1");
    expect(await screen.findByRole("heading", { name: "Draft body" })).toBeTruthy();
  });

  it("opens ?rev=N", async () => {
    renderReport("/ws/w/reports/r1?rev=1");
    expect(await screen.findByRole("heading", { name: "Published body" })).toBeTruthy();
    expect(m.getRevision).toHaveBeenCalledWith("w", "r1", 1);
  });

  it("opens the latest when nothing is published", async () => {
    m.getReport.mockResolvedValue(report({ published_rev: null }));
    renderReport();
    expect(await screen.findByRole("heading", { name: "Draft body" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /view live/ })).toBeNull();
  });

  it("lists revisions and diffs two of them", async () => {
    renderReport();
    await screen.findByRole("heading", { name: "Published body" });
    expect(screen.getByText("first")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    await waitFor(() => expect(screen.getByText("+ new line")).toBeTruthy());
    expect(screen.getByText("- # Published body")).toBeTruthy();
  });

  it("shows the report comment thread", async () => {
    renderReport();
    await screen.findByRole("heading", { name: "Published body" });
    await waitFor(() => expect(m.listComments).toHaveBeenCalledWith("w", "report:r1"));
  });

  it("renders the published revision's panels from their published data", async () => {
    renderReport();
    await screen.findByRole("heading", { name: "Published body" });
    expect(document.getElementById("p-loss")?.textContent).toBe("panel loss frozen 1");
  });

  it("lets editors publish the draft with the panels' captured data", async () => {
    m.getReport.mockResolvedValue(report({ can_edit: true }));
    m.publish.mockResolvedValue({ rev: 2 });
    renderReport();
    await screen.findByRole("heading", { name: "Draft body" });
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(m.publish).toHaveBeenCalledWith("w", "r1", { rev: 2, data: {} }));
  });

  it("hides Publish from viewers", async () => {
    renderReport("/ws/w/reports/r1?live=1");
    await screen.findByRole("heading", { name: "Draft body" });
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
  });
});
