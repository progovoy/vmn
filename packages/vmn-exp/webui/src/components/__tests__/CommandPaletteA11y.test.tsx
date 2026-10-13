import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { useState } from "react";

vi.mock("../../api", () => ({
  api: { recentExperiments: vi.fn(), experimentsPaged: vi.fn(), apps: vi.fn() },
  appTag: (n: string) => n.replaceAll("/", "-"),
  appName: (t: string) => t.replaceAll("-", "/"),
}));
vi.mock("../../apiModels", () => ({ apiModels: { listModels: vi.fn(() => Promise.resolve({ models: [] })) } }));
vi.mock("../../apiReports", () => ({ apiReports: { listReports: vi.fn(() => Promise.resolve({ reports: [] })) } }));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import CommandPalette from "../CommandPalette";
import { fakeCtx } from "../palette/__tests__/fakeCtx";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const writeText = vi.fn(() => Promise.resolve());

function Where() {
  const loc = useLocation();
  return <span data-testid="where">{loc.pathname + loc.search}</span>;
}

function Harness({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>opener</button>
      {open && <CommandPalette ctx={fakeCtx()} onClose={() => { onClose(); setOpen(false); }} />}
    </>
  );
}

function openPalette(onClose?: () => void) {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Routes><Route path="*" element={<><Harness onClose={onClose} /><Where /></>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const opener = screen.getByRole("button", { name: "opener" });
  opener.focus();
  fireEvent.click(opener);
  return { opener, input: screen.getByRole("combobox"), dialog: screen.getByRole("dialog") };
}

const activeOption = () => {
  const id = screen.getByRole("combobox").getAttribute("aria-activedescendant")!;
  return document.getElementById(id)!;
};
const key = (el: HTMLElement, k: string, opts: Partial<KeyboardEventInit> = {}) =>
  fireEvent.keyDown(el, { key: k, ...opts });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.recentExperiments.mockResolvedValue([
    { idx: 2, verstr: "0.0.2-dev.b", timestamp: null, note: null },
    { idx: 1, verstr: "0.0.1-dev.a", timestamp: null, note: null },
  ]);
  m.apps.mockResolvedValue([{ name: "app", experiments: 2, versions: 0 }]);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
});
afterEach(() => vi.restoreAllMocks());

describe("CommandPalette semantics", () => {
  it("is a modal dialog holding a combobox that controls a grouped listbox", async () => {
    const { dialog, input } = openPalette();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("Command palette");
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-controls", "cmdk-list");
    expect(input).toHaveAttribute("aria-autocomplete", "list");
    expect(input).toHaveAccessibleDescription(/↑↓ move · ↵ open · ⌘↵ new tab · ⇧↵ copy CLI · tab complete · esc close/);
    expect(screen.getByRole("listbox")).toHaveAttribute("id", "cmdk-list");
    expect(screen.getByRole("group", { name: "Go to" })).toBeInTheDocument();
    await screen.findByRole("group", { name: "Runs" });
    const first = screen.getAllByRole("option")[0];
    expect(input).toHaveAttribute("aria-activedescendant", first.id);
    expect(first).toHaveAttribute("aria-selected", "true");
  });

  it("announces the result count politely", async () => {
    openPalette();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/^\d+ results$/));
  });

  it("moves with the arrows (wrapping), Home and End", () => {
    const { input } = openPalette();
    const options = () => screen.getAllByRole("option");
    key(input, "ArrowDown");
    expect(activeOption()).toBe(options()[1]);
    expect(options()[1]).toHaveAttribute("aria-selected", "true");
    key(input, "Home");
    key(input, "ArrowUp");
    expect(activeOption()).toBe(options()[options().length - 1]);
    key(input, "Home");
    expect(activeOption()).toBe(options()[0]);
    key(input, "End");
    expect(activeOption()).toBe(options()[options().length - 1]);
  });

  it("jumps between sections with PageDown and PageUp", async () => {
    const { input } = openPalette();
    await screen.findByText("0.0.2-dev.b");
    key(input, "PageDown");
    const runs = screen.getByRole("group", { name: "Runs" });
    expect(within(runs).getAllByRole("option")[0]).toBe(activeOption());
    key(input, "PageUp");
    expect(activeOption()).toBe(screen.getAllByRole("option")[0]);
  });
});

describe("CommandPalette keys", () => {
  it("traps focus while open and gives it back to the opener on close", () => {
    const { opener, input } = openPalette();
    expect(input).toHaveFocus();
    key(input, "Tab");
    expect(input).toHaveFocus();
    key(input, "Tab", { shiftKey: true });
    expect(input).toHaveFocus();
    key(input, "Escape");
    expect(opener).toHaveFocus();
  });

  it("Esc clears the input first, then closes", () => {
    const onClose = vi.fn();
    const { input } = openPalette(onClose);
    fireEvent.change(input, { target: { value: "abc" } });
    key(input, "Escape");
    expect(input).toHaveValue("");
    expect(onClose).not.toHaveBeenCalled();
    key(input, "Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("says what Esc does: clear while there is text, then close again", () => {
    const { input } = openPalette();
    const foot = () => document.querySelector(".cmdk-foot")!.textContent;
    expect(foot()).toMatch(/esc close$/);
    fireEvent.change(input, { target: { value: "abc" } });
    expect(foot()).toMatch(/esc clear$/);
    expect(input).toHaveAccessibleDescription(/esc clear$/);
    key(input, "Escape");
    expect(foot()).toMatch(/esc again to close$/);
    expect(input).toHaveAccessibleDescription(/esc again to close$/);
  });

  it("Enter goes to the active row and closes", () => {
    const onClose = vi.fn();
    const { input } = openPalette(onClose);
    key(input, "Enter");
    expect(screen.getByTestId("where")).toHaveTextContent("/ws/w/app/app");
    expect(onClose).toHaveBeenCalled();
  });

  it("Shift+Enter copies the row's CLI instead of going", async () => {
    const { input } = openPalette();
    key(input, "Enter", { shiftKey: true });
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("vmn-exp list app"));
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
    expect(await screen.findByRole("status")).toHaveTextContent("Copied vmn-exp list app");
  });

  it("Cmd/Ctrl+Enter opens the row in a new tab", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const { input } = openPalette();
    key(input, "Enter", { metaKey: true });
    expect(open).toHaveBeenCalledWith("/ws/w/app/app", "_blank", "noopener");
    key(input, "ArrowDown");
    key(input, "Enter", { ctrlKey: true });
    expect(open).toHaveBeenLastCalledWith("/ws/w/app/app/tree", "_blank", "noopener");
  });

  it("Tab completes the verb, then the app", async () => {
    const { input } = openPalette();
    fireEvent.change(input, { target: { value: "sh" } });
    key(input, "Tab");
    expect(input).toHaveValue("show ");
    await waitFor(() => expect(m.apps).toHaveBeenCalled());
    await act(async () => {});
    fireEvent.change(input, { target: { value: "show ap" } });
    key(input, "Tab");
    expect(input).toHaveValue("show app ");
  });

  it("a template row fills the input instead of going", () => {
    const { input } = openPalette();
    fireEvent.click(screen.getByText("Compare runs…"));
    expect(input).toHaveValue("compare ");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
  });

  it("N more expands its section in place", () => {
    openPalette();
    const goto = screen.getByRole("group", { name: "Go to" });
    const more = within(goto).getByText(/^\d+ more$/);
    expect(within(goto).queryByText("Models")).toBeNull();
    fireEvent.click(more);
    expect(within(goto).getByText("Models")).toBeInTheDocument();
  });

  it("explains a miss with the grammar", async () => {
    const { input } = openPalette();
    m.experimentsPaged.mockResolvedValue({ rows: [], total: 0 });
    fireEvent.change(input, { target: { value: "xyzzy" } });
    expect(await screen.findByText(
      'No match for "xyzzy". Try @12, show -v <verstr>, compare @3 @7, or metrics.loss < 0.3.',
    )).toBeInTheDocument();
  });

  it("names the veil class that follows the theme", () => {
    openPalette();
    expect(document.querySelector(".cmdk-veil")).not.toBeNull();
    expect(document.querySelector(".palette-veil")).toBeNull();
  });
});
