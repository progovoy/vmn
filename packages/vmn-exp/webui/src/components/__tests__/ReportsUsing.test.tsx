import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiReports", async (orig) => ({
  ...(await orig<typeof import("../../apiReports")>()),
  apiReports: { reportsUsing: vi.fn() },
}));

import { apiReports } from "../../apiReports";
import ReportsUsing from "../ReportsUsing";

const m = apiReports as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => vi.clearAllMocks());

const show = (verstr?: string) =>
  renderWithClient(<MemoryRouter><ReportsUsing ws="w" app="root/svc" verstr={verstr} /></MemoryRouter>);

describe("ReportsUsing", () => {
  it("links every report using the run", async () => {
    m.reportsUsing.mockResolvedValue({ reports: [{ rid: "r1", rev: 2, title: "Ablation" }] });
    show("1.0.0");
    const link = await screen.findByRole("link", { name: "Ablation" });
    expect(link.getAttribute("href")).toBe("/ws/w/reports/r1");
    expect(m.reportsUsing).toHaveBeenCalledWith("w", "root/svc", "1.0.0");
  });

  it("renders nothing when no report uses it", async () => {
    m.reportsUsing.mockResolvedValue({ reports: [] });
    const { container } = show();
    await vi.waitFor(() => expect(m.reportsUsing).toHaveBeenCalledWith("w", "root/svc", undefined));
    expect(container.textContent).toBe("");
  });
});
