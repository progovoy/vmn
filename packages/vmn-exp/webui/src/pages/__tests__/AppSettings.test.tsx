/** Plan 28 A0: the app settings page edits the store settings' YAML. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiSettings", () => ({ apiSettings: { get: vi.fn(), save: vi.fn() } }));
const scope = vi.fn();
vi.mock("../../shell/usePageScope", () => ({ usePageScope: () => scope() }));

import { apiSettings } from "../../apiSettings";
import AppSettings from "../AppSettings";

const api = apiSettings as unknown as Record<"get" | "save", ReturnType<typeof vi.fn>>;
const TEXT = "ui: {group_aggregate: best}\n";
const SAVED = {
  text: TEXT, settings: { ui: { group_aggregate: "best" } }, error: null,
  updated_at: "2026-10-28T10:00:00Z", updated_by: { id: "u1", name: "Ada" },
};

function renderPage() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/w/app/root-svc/settings"]}>
      <Routes><Route path="/ws/:ws/app/:app/settings" element={<AppSettings />} /></Routes>
    </MemoryRouter>,
  );
}

const editor = () => screen.findByLabelText("Settings YAML") as Promise<HTMLTextAreaElement>;

beforeEach(() => {
  vi.clearAllMocks();
  scope.mockReturnValue({ readOnly: false, readOnlyReason: null });
  api.get.mockResolvedValue(SAVED);
});

describe("AppSettings page", () => {
  it("shows the app's settings text and who saved it last", async () => {
    renderPage();
    expect((await editor()).value).toBe(TEXT);
    expect(api.get).toHaveBeenCalledWith("w", "root/svc");
    expect(screen.getByText(/Ada/)).toBeInTheDocument();
  });

  it("saves the edited text", async () => {
    api.save.mockResolvedValue({ ...SAVED, text: "ui: {stale_after_min: 9}\n" });
    renderPage();
    const box = await editor();
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.change(box, { target: { value: "ui: {stale_after_min: 9}\n" } });
    fireEvent.click(save);
    await waitFor(() => expect(api.save).toHaveBeenCalledWith("w", "root/svc", "ui: {stale_after_min: 9}\n"));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("shows why the server refused the settings, keeping the edit", async () => {
    api.save.mockRejectedValue(Object.assign(new Error("invalid ui.group_aggregate: 'sum'"), { status: 400 }));
    renderPage();
    const box = await editor();
    fireEvent.change(box, { target: { value: "ui: {group_aggregate: sum}\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid ui.group_aggregate: 'sum'");
    expect(box.value).toBe("ui: {group_aggregate: sum}\n");
  });

  it("says when the stored file does not parse", async () => {
    api.get.mockResolvedValue({ ...SAVED, settings: {}, error: "not valid YAML: boom" });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("not valid YAML: boom");
  });

  it("is read-only for a viewer or a read-only server, saying why", async () => {
    scope.mockReturnValue({ readOnly: true, readOnlyReason: "Your role in w is viewer" });
    renderPage();
    expect((await editor()).readOnly).toBe(true);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.getByText("Your role in w is viewer")).toBeInTheDocument();
  });

  it("shows a failed read as an error", async () => {
    api.get.mockRejectedValue(Object.assign(new Error("store unavailable"), { status: 503 }));
    renderPage();
    expect(await screen.findByText(/store unavailable/)).toBeInTheDocument();
  });
});
