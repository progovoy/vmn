import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiReports", async (orig) => ({
  ...(await orig<typeof import("../../apiReports")>()),
  apiReports: { getReport: vi.fn(), saveRevision: vi.fn(), getRevision: vi.fn() },
}));
vi.mock("../../reports/Panel", () => ({ default: () => <div>panel-body</div>, PanelError: () => null }));

import { apiReports } from "../../apiReports";
import ReportEdit, { DRAFT_SAVE_MS } from "../ReportEdit";

const getReport = apiReports.getReport as unknown as ReturnType<typeof vi.fn>;
const saveRevision = apiReports.saveRevision as unknown as ReturnType<typeof vi.fn>;
const getRevision = apiReports.getRevision as unknown as ReturnType<typeof vi.fn>;
const conflict = (rev: number, body: string) =>
  Object.assign(new Error("conflict"), { status: 409, body: { rev, body, author: "bob" } });
const KEY = "vmn_report_draft:w/r1";
const BODY = "# Hi\n\n```vmn-panel\nv: 1\nid: p1\ntype: bar\napp: a\nruns: {query: x = 1}\nmetric: m\n```\n";

function renderEdit() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/w/reports/r1/edit"]}>
      <Routes><Route path="/ws/:ws/reports/:rid/edit" element={<ReportEdit />} /></Routes>
    </MemoryRouter>,
  );
}
const editor = () => screen.getByLabelText("Report source") as HTMLTextAreaElement;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  getReport.mockResolvedValue({ rid: "r1", title: "T", rev: 3, body: BODY });
  saveRevision.mockResolvedValue({ rev: 4 });
});
afterEach(() => vi.useRealTimers());

describe("ReportEdit", () => {
  it("shows source and live preview", async () => {
    renderEdit();
    await waitFor(() => expect(editor().value).toBe(BODY));
    fireEvent.change(editor(), { target: { value: "# Changed" } });
    expect(screen.getByRole("heading", { name: "Changed" })).toBeTruthy();
  });

  it("autosaves the draft and restores it on reload", async () => {
    const first = renderEdit();
    await waitFor(() => expect(editor().value).toBe(BODY));
    vi.useFakeTimers();
    fireEvent.change(editor(), { target: { value: "draft text" } });
    act(() => { vi.advanceTimersByTime(DRAFT_SAVE_MS + 10); });
    vi.useRealTimers();
    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ body: "draft text", base: 3 });
    first.unmount();
    renderEdit();
    await waitFor(() => expect(editor().value).toBe("draft text"));
  });

  it("saves a revision with base and message on Ctrl+S and clears the draft", async () => {
    renderEdit();
    await waitFor(() => expect(editor().value).toBe(BODY));
    fireEvent.change(editor(), { target: { value: "new body" } });
    fireEvent.change(screen.getByLabelText("Revision message"), { target: { value: "tweak" } });
    fireEvent.keyDown(editor(), { key: "s", ctrlKey: true });
    await waitFor(() => expect(saveRevision).toHaveBeenCalledWith("w", "r1", { base: 3, body: "new body", message: "tweak" }));
    await waitFor(() => expect(localStorage.getItem(KEY)).toBeNull());
  });

  it("inserts a panel block via the dialog", async () => {
    renderEdit();
    await waitFor(() => expect(editor().value).toBe(BODY));
    fireEvent.click(screen.getByRole("button", { name: "Insert panel" }));
    fireEvent.change(screen.getByLabelText("App"), { target: { value: "zz" } });
    fireEvent.change(screen.getByLabelText("Filter query"), { target: { value: "a = 1" } });
    fireEvent.change(screen.getByLabelText("Metric"), { target: { value: "acc" } });
    fireEvent.click(screen.getByRole("button", { name: "Insert" }));
    expect(editor().value).toContain("app: zz");
    expect(editor().value.match(/```vmn-panel/g)).toHaveLength(2);
  });

  it("gear edits a previewed panel in place", async () => {
    renderEdit();
    await waitFor(() => expect(editor().value).toBe(BODY));
    fireEvent.click(screen.getByRole("button", { name: "Edit panel p1" }));
    fireEvent.change(screen.getByLabelText("Metric"), { target: { value: "loss" } });
    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    expect(editor().value).toContain("metric: loss");
    expect(editor().value).not.toContain("metric: m\n");
    expect(editor().value.match(/```vmn-panel/g)).toHaveLength(1);
  });

  it("on 409 auto-merges non-overlapping edits and retries with the new base", async () => {
    getReport.mockResolvedValue({ rid: "r1", title: "T", rev: 3, body: "a\nb\nc" });
    getRevision.mockResolvedValue({ rev: 3, body: "a\nb\nc" });
    saveRevision.mockRejectedValueOnce(conflict(5, "A\nb\nc")).mockResolvedValueOnce({ rev: 6 });
    renderEdit();
    await waitFor(() => expect(editor().value).toBe("a\nb\nc"));
    fireEvent.change(editor(), { target: { value: "a\nb\nC" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(saveRevision).toHaveBeenLastCalledWith("w", "r1", { base: 5, body: "A\nb\nC" }));
    expect(getRevision).toHaveBeenCalledWith("w", "r1", 3);
    await waitFor(() => expect(editor().value).toBe("A\nb\nC"));
    expect(screen.getByRole("status").textContent).toContain("merged");
  });

  it("on 409 with overlapping edits shows the resolve view and saves on the new base", async () => {
    getReport.mockResolvedValue({ rid: "r1", title: "T", rev: 3, body: "a\nb\nc" });
    getRevision.mockResolvedValue({ rev: 3, body: "a\nb\nc" });
    saveRevision.mockRejectedValueOnce(conflict(5, "a\nT\nc")).mockResolvedValueOnce({ rev: 6 });
    renderEdit();
    await waitFor(() => expect(editor().value).toBe("a\nb\nc"));
    fireEvent.change(editor(), { target: { value: "a\nY\nc" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const view = await screen.findByRole("region", { name: "Resolve conflicts" });
    expect(view.textContent).toContain("T");
    expect(view.textContent).toContain("Y");
    fireEvent.click(screen.getByRole("radio", { name: "Hunk 1: both" }));
    const result = screen.getByLabelText("Merged result") as HTMLTextAreaElement;
    expect(result.value).toBe("a\nT\nY\nc");
    fireEvent.change(result, { target: { value: "a\nTY\nc" } });
    fireEvent.click(screen.getByRole("button", { name: "Save resolved" }));
    await waitFor(() => expect(saveRevision).toHaveBeenLastCalledWith("w", "r1", { base: 5, body: "a\nTY\nc" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Resolve conflicts" })).toBeNull());
    expect(editor().value).toBe("a\nTY\nc");
  });
});
