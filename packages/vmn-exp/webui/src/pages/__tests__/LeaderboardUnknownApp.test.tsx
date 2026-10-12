import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";
import type { Meta, Workspace } from "../../types";

const meta = vi.fn<() => Promise<Meta>>();
const workspaces = vi.fn<() => Promise<Workspace[]>>();
const apps = vi.fn();
const appStatus = vi.fn();
vi.mock("../../api", () => ({
  api: {
    experiments: () => Promise.resolve([]),
    metricsSchema: () => Promise.resolve({}),
    meta: () => meta(), workspaces: () => workspaces(), apps: () => apps(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../apiShell", () => ({ apiShell: { appStatus: () => appStatus() } }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));

import Leaderboard from "../Leaderboard";

const never = () => new Promise<never>(() => {});
const status = (total: number) => ({
  total, counts: { created: 0, running: 0, stuck: 0, succeeded: total, failed: 0 },
  failed_recent: 0, rollup: null,
});

function renderBoard(ws = "ml-repo") {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/${ws}/app/ml_app`]}>
      <Routes><Route path="/ws/:ws/app/:app" element={<Leaderboard />} /></Routes>
    </MemoryRouter>,
  );
}

/** Let every mocked read resolve and render before asserting an absence. */
const settle = () => act(() => new Promise((r) => setTimeout(r, 30)));
const newRun = () => screen.queryByRole("button", { name: "New run" });

beforeEach(() => {
  vi.clearAllMocks();
  meta.mockResolvedValue({ version: "1" });
  workspaces.mockResolvedValue([
    { name: "ml-repo", kind: "git", path: "/r" }, { name: "team", kind: "store", store: "s3://t" },
  ]);
  apps.mockResolvedValue([{ name: "ml_app", experiments: 0, versions: 1 }]);
  appStatus.mockResolvedValue(status(0));
});

describe("Leaderboard empty state", () => {
  it("says no runs yet and offers the CLI and a New run button for a known app", async () => {
    renderBoard();
    expect(await screen.findByText(/No runs yet in ml_app/)).toBeInTheDocument();
    expect(screen.getByText("vmn-exp create ml_app")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "New run" })).toBeInTheDocument();
  });

  it("offers no New run while the app's existence is unknown", async () => {
    appStatus.mockReturnValue(never());
    renderBoard();
    await screen.findByText(/No runs yet in ml_app/);
    await settle();
    expect(newRun()).toBeNull();
  });

  it("offers New run from the status answer alone, whatever the app list says", async () => {
    apps.mockResolvedValue([]);
    renderBoard();
    await screen.findByText(/No runs yet in ml_app/);
    await settle();
    expect(newRun()).not.toBeNull();
  });

  it("offers no New run for an app the server does not know", async () => {
    appStatus.mockRejectedValue(
      Object.assign(new Error("x"), { status: 404, body: { detail: "x", code: "app_not_found" } }),
    );
    renderBoard();
    await screen.findByText(/No runs yet in ml_app/);
    await waitFor(() => expect(appStatus).toHaveBeenCalled());
    await settle();
    expect(newRun()).toBeNull();
  });

  it("offers no New run on a read-only server", async () => {
    meta.mockResolvedValue({ version: "1", read_only: true });
    renderBoard();
    await screen.findByText(/No runs yet in ml_app/);
    await waitFor(() => expect(meta).toHaveBeenCalled());
    await waitFor(() => expect(appStatus).toHaveBeenCalled());
    await settle();
    expect(newRun()).toBeNull();
  });

  it("offers no New run in a store workspace", async () => {
    renderBoard("team");
    await screen.findByText(/No runs yet in ml_app/);
    await waitFor(() => expect(workspaces).toHaveBeenCalled());
    await waitFor(() => expect(appStatus).toHaveBeenCalled());
    await settle();
    expect(newRun()).toBeNull();
  });
});
