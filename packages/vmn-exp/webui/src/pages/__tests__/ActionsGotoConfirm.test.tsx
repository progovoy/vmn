import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api", () => ({
  api: { apps: vi.fn(), versions: vi.fn(), action: vi.fn(), job: vi.fn() },
  appTag: (n: string) => n.replaceAll("/", "-"),
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import Actions from "../Actions";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function renderAt(url: string) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes><Route path="/ws/:ws/app/:app/actions" element={<Actions />} /></Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.apps.mockResolvedValue([{ name: "ml_app", experiments: 1, versions: 2 }]);
  m.versions.mockResolvedValue([{ verstr: "1.2.0", kind: "version" }]);
  m.action.mockResolvedValue({ id: "j1", action: "goto", status: "running", log: "" });
  m.job.mockResolvedValue({ id: "j1", action: "goto", status: "running", log: "" });
});

const gotoButton = () => screen.getByRole("button", { name: "Goto" });

describe("Actions goto confirmation", () => {
  it("opens a confirm dialog with the command instead of running goto", async () => {
    renderAt("/ws/w/app/ml_app/actions?goto=1.2.0");
    await waitFor(() => expect(m.versions).toHaveBeenCalled());
    fireEvent.click(gotoButton());
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("vmn goto -v 1.2.0 ml_app")).toBeInTheDocument();
    expect(within(dialog).getByText(/other apps in this repo are untouched/i)).toBeInTheDocument();
    expect(m.action).not.toHaveBeenCalled();
  });

  it("runs goto only once the dialog is confirmed", async () => {
    renderAt("/ws/w/app/ml_app/actions?goto=1.2.0");
    fireEvent.click(gotoButton());
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Run goto" }));
    await waitFor(() => expect(m.action).toHaveBeenCalledTimes(1));
    expect(m.action).toHaveBeenCalledWith("w", "ml_app", "goto", { verstr: "1.2.0" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancelling runs nothing and closes the dialog", async () => {
    renderAt("/ws/w/app/ml_app/actions?goto=1.2.0");
    fireEvent.click(gotoButton());
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(m.action).not.toHaveBeenCalled();
  });

  it("names the branch tip when the version is empty", () => {
    renderAt("/ws/w/app/ml_app/actions");
    fireEvent.click(gotoButton());
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("vmn goto ml_app")).toBeInTheDocument();
    expect(within(dialog).getByText(/tip of the current branch/i)).toBeInTheDocument();
  });

  it("gives Goto the same weight as Preview", () => {
    renderAt("/ws/w/app/ml_app/actions");
    const preview = screen.getByRole("button", { name: "Preview" });
    expect(gotoButton().className).toBe(preview.className);
  });

  it("stamp needs no confirmation", async () => {
    renderAt("/ws/w/app/ml_app/actions");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(m.action).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
