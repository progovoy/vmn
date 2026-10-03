import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiReports", async (orig) => ({
  ...(await orig<typeof import("../../apiReports")>()),
  apiReports: { listReports: vi.fn(), createReport: vi.fn() },
}));

import { apiReports } from "../../apiReports";
import Reports from "../Reports";

const listReports = apiReports.listReports as unknown as ReturnType<typeof vi.fn>;

function renderReports() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/w/reports"]}>
      <Routes>
        <Route path="/ws/:ws/reports" element={<Reports />} />
        <Route path="/ws/:ws/reports/:rid/edit" element={<div>editor-page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  listReports.mockResolvedValue({
    reports: [
      { rid: "r1", title: "LR sweep", created_by: "ann", author: "bob", rev: 2,
        created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z",
        published_rev: 1, archived: false, pinned: false },
      { rid: "r2", title: "Draft only", created_by: "cat", rev: 1, published_rev: null,
        archived: false, pinned: false },
    ],
  });
});

describe("Reports page", () => {
  it("lists title, author and published state with links", async () => {
    renderReports();
    const link = await screen.findByRole("link", { name: "LR sweep" });
    expect(link.getAttribute("href")).toBe("/ws/w/reports/r1");
    expect(screen.getByText("bob")).toBeTruthy();
    expect(screen.getByText("v1")).toBeTruthy();
    expect(screen.getByText("Draft only")).toBeTruthy();
    expect(listReports).toHaveBeenCalledWith("w", false);
  });

  it("refetches with the archived filter", async () => {
    renderReports();
    await screen.findByText("LR sweep");
    fireEvent.click(screen.getByLabelText("Show archived"));
    await waitFor(() => expect(listReports).toHaveBeenCalledWith("w", true));
  });

  it("creates a new report and opens its editor", async () => {
    (apiReports.createReport as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ rid: "r9", rev: 1 });
    renderReports();
    await screen.findByText("LR sweep");
    fireEvent.change(screen.getByLabelText("New report title"), { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: "New report" }));
    await screen.findByText("editor-page");
    expect(apiReports.createReport).toHaveBeenCalledWith("w", { title: "Fresh", body: "" });
  });
});
