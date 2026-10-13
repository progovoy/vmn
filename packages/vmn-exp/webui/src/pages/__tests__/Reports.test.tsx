import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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
    const toggle = screen.getByRole("button", { name: "archived" });
    expect(toggle).toHaveClass("status-toggle");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    await waitFor(() => expect(listReports).toHaveBeenCalledWith("w", true));
    expect(toggle).toHaveAttribute("aria-pressed", "true");
  });

  it("drops the redundant workspace subtitle", async () => {
    renderReports();
    await screen.findByText("LR sweep");
    expect(screen.getByRole("heading", { level: 1, name: "Reports" })).toBeInTheDocument();
    expect(document.querySelector(".page-head .what")).toBeNull();
  });

  it("asks for the title in a labelled New report dialog", async () => {
    renderReports();
    await screen.findByText("LR sweep");
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "New report" }));
    const dialog = screen.getByRole("dialog", { name: "New report" });
    const title = within(dialog).getByLabelText("Title");
    expect(title.tagName).toBe("INPUT");
    const label = dialog.querySelector(`label[for="${title.id}"]`) ?? title.closest("label");
    expect(label?.textContent).toMatch(/^Title/);
    expect(label).not.toHaveClass("sr-only");
    expect(title).toHaveFocus();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apiReports.createReport).not.toHaveBeenCalled();
  });

  it("creates a new report and opens its editor", async () => {
    (apiReports.createReport as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ rid: "r9", rev: 1 });
    renderReports();
    await screen.findByText("LR sweep");
    fireEvent.click(screen.getByRole("button", { name: "New report" }));
    const dialog = screen.getByRole("dialog", { name: "New report" });
    fireEvent.change(within(dialog).getByLabelText("Title"), { target: { value: "Fresh" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await screen.findByText("editor-page");
    expect(apiReports.createReport).toHaveBeenCalledWith("w", { title: "Fresh", body: "" });
  });
});
