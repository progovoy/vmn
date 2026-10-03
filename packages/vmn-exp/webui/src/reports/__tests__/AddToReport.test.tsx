import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiReports", () => ({
  apiReports: { listReports: vi.fn(), getReport: vi.fn(), saveRevision: vi.fn(), createReport: vi.fn() },
}));

import { apiReports } from "../../apiReports";
import { appendPanel } from "../appendPanel";
import AddToReport from "../AddToReport";
import { specToBlock } from "../panelBlocks";
import type { PanelSpec } from "../panelSpec";

const m = apiReports as unknown as Record<string, ReturnType<typeof vi.fn>>;
const spec: PanelSpec = { v: 1, id: "p1", type: "run", app: "a", runs: { verstrs: ["x"] } };
const conflict = () => Object.assign(new Error("conflict"), { status: 409, body: { rev: 3 } });

beforeEach(() => {
  vi.clearAllMocks();
  m.listReports.mockResolvedValue({ reports: [{ rid: "r1", title: "Weekly", rev: 2 }] });
  m.getReport.mockResolvedValue({ rid: "r1", rev: 2, body: "# Weekly\n" });
  m.saveRevision.mockResolvedValue({ rev: 3 });
  m.createReport.mockResolvedValue({ rid: "r9", rev: 1 });
});

describe("appendPanel", () => {
  it("appends the block to the latest revision", async () => {
    await expect(appendPanel("w", "r1", spec)).resolves.toBe(3);
    expect(m.saveRevision).toHaveBeenCalledWith("w", "r1", {
      base: 2, body: "# Weekly\n\n" + specToBlock(spec), message: "add panel p1",
    });
  });

  it("on 409 refetches the latest and appends to it", async () => {
    m.saveRevision.mockRejectedValueOnce(conflict()).mockResolvedValueOnce({ rev: 4 });
    m.getReport.mockResolvedValueOnce({ rid: "r1", rev: 2, body: "old\n" })
      .mockResolvedValueOnce({ rid: "r1", rev: 3, body: "new\n" });
    await expect(appendPanel("w", "r1", spec)).resolves.toBe(4);
    expect(m.saveRevision).toHaveBeenLastCalledWith("w", "r1", expect.objectContaining({
      base: 3, body: "new\n\n" + specToBlock(spec),
    }));
  });

  it("gives up after repeated conflicts", async () => {
    m.saveRevision.mockRejectedValue(conflict());
    await expect(appendPanel("w", "r1", spec)).rejects.toThrow("conflict");
  });

  it("rethrows other errors", async () => {
    m.saveRevision.mockRejectedValue(Object.assign(new Error("nope"), { status: 403 }));
    await expect(appendPanel("w", "r1", spec)).rejects.toThrow("nope");
    expect(m.saveRevision).toHaveBeenCalledTimes(1);
  });
});

const open = () => {
  renderWithClient(<MemoryRouter><AddToReport ws="w" spec={() => spec} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Add to report" }));
};

describe("AddToReport", () => {
  it("appends to a picked report", async () => {
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Weekly" }));
    expect(await screen.findByRole("link", { name: /Weekly/ })).toHaveAttribute("href", "/ws/w/reports/r1");
    expect(m.saveRevision).toHaveBeenCalledWith("w", "r1", expect.objectContaining({ base: 2 }));
  });

  it("creates a new report holding the block", async () => {
    open();
    fireEvent.change(await screen.findByLabelText("New report title"), { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(m.createReport).toHaveBeenCalledWith("w", { title: "Fresh", body: specToBlock(spec) }));
    expect(await screen.findByRole("link", { name: /Fresh/ })).toHaveAttribute("href", "/ws/w/reports/r9");
  });

  it("shows a failure", async () => {
    m.saveRevision.mockRejectedValue(new Error("boom"));
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Weekly" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });

  it("is hidden when the view has no panel", () => {
    renderWithClient(<MemoryRouter><AddToReport ws="w" spec={() => null} /></MemoryRouter>);
    expect(screen.queryByRole("button", { name: "Add to report" })).toBeNull();
  });
});
