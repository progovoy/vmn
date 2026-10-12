import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";
import type { AppRow, Meta, Workspace } from "../../types";
import type { AppStatus } from "../../shell/contracts";

const meta = vi.fn<() => Promise<Meta>>();
const workspaces = vi.fn<() => Promise<Workspace[]>>();
const apps = vi.fn<(ws: string) => Promise<AppRow[]>>();
vi.mock("../../api", async (orig) => ({
  ...(await orig<typeof import("../../api")>()),
  api: { meta: () => meta(), workspaces: () => workspaces(), apps: (ws: string) => apps(ws) },
}));
const appStatus = vi.fn<(ws: string, tag: string) => Promise<AppStatus>>();
vi.mock("../../apiShell", () => ({
  apiShell: { appStatus: (ws: string, tag: string) => appStatus(ws, tag) },
}));
const cacheStatus = vi.fn();
vi.mock("../../apiCache", async (orig) => ({
  ...(await orig<typeof import("../../apiCache")>()),
  apiCache: { status: (ws: string) => cacheStatus(ws), resync: vi.fn() },
}));

import { AppsPage } from "../Dashboard";

const WS: Workspace[] = [
  { name: "ml-repo", kind: "git", path: "/srv/checkouts/ml-repo" },
  { name: "shared", kind: "store", store: "s3://bucket/vmn" },
];
const zero = { created: 0, running: 0, stuck: 0, succeeded: 0, failed: 0 };
const status = (over: Partial<AppStatus["counts"]> = {}): AppStatus => ({
  total: 1, counts: { ...zero, ...over }, failed_recent: 0,
  rollup: over.stuck ? "stuck" : over.running ? "running" : null,
});
const idleCache = { workspace: "ml-repo", state: "idle", progress: { done: 0, total: 0 },
  drift: 0, rebuilds: 0, last_rebuild_reason: null, journal_lag_sec: 0, apps: {} };

function renderAt(ws: string) {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/${ws}`]}>
      <Routes><Route path="/ws/:ws" element={<AppsPage />} /></Routes>
    </MemoryRouter>,
  );
}

async function settled() {
  await vi.waitFor(() => expect(meta).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 0));
}

beforeEach(() => {
  vi.clearAllMocks();
  meta.mockResolvedValue({ version: "0.10.2" });
  workspaces.mockResolvedValue(WS);
  appStatus.mockResolvedValue(status());
  cacheStatus.mockResolvedValue(idleCache);
  apps.mockResolvedValue([
    { name: "clf", experiments: 53, versions: 12 },
    { name: "root/svc", experiments: 1, versions: 1 },
  ]);
});

describe("AppsPage", () => {
  it("heads the page with the workspace, its app count, kind and location", async () => {
    renderAt("ml-repo");
    expect(await screen.findByRole("heading", { level: 1, name: "ml-repo" })).toBeTruthy();
    expect(await screen.findByText("2 apps · git · /srv/checkouts/ml-repo")).toBeTruthy();
  });

  it("counts runs and versions on each tile, linked by the name", async () => {
    renderAt("ml-repo");
    const link = await screen.findByRole("link", { name: "clf" });
    expect(link.getAttribute("href")).toBe("/ws/ml-repo/app/clf");
    const tile = link.closest("article.app-tile") as HTMLElement;
    expect(within(tile).getByText("53 runs · 12 versions")).toBeTruthy();
    const other = screen.getByRole("link", { name: "root/svc" });
    expect(other.getAttribute("href")).toBe("/ws/ml-repo/app/root-svc");
    expect(within(other.closest("article")!).getByText("1 run · 1 version")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/experiment/);
  });

  it("omits versions in a store workspace", async () => {
    renderAt("shared");
    expect(await screen.findByText("2 apps · store · s3://bucket/vmn")).toBeTruthy();
    expect(screen.getByText("53 runs")).toBeTruthy();
    expect(screen.queryByText(/versions?/)).toBeNull();
  });

  it("shows each app's status rollup, linked to its leaderboard", async () => {
    appStatus.mockImplementation(async (_ws, tag) =>
      tag === "clf" ? status({ stuck: 2, running: 3 }) : status());
    renderAt("ml-repo");
    const stuck = await screen.findByRole("link", { name: "2 stuck" });
    expect(stuck.getAttribute("href")).toBe("/ws/ml-repo/app/clf?status=stuck");
    expect(stuck.closest("article")!.querySelector(".ws-tile-link, .app-tile-link")!.textContent)
      .toBe("clf");
    expect(appStatus).toHaveBeenCalledWith("ml-repo", "clf");
    expect(appStatus).toHaveBeenCalledWith("ml-repo", "root-svc");
    expect(document.querySelector(".status-dot")).toBeNull();
  });

  it("requests a tile's status only once it scrolls into view", async () => {
    const observed: Element[] = [];
    vi.stubGlobal("IntersectionObserver", class {
      observe(el: Element) { observed.push(el); }
      disconnect() {}
    });
    try {
      renderAt("ml-repo");
      await screen.findByRole("link", { name: "clf" });
      await new Promise((r) => setTimeout(r, 0));
      expect(observed.length).toBe(2);
      expect(appStatus).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("shows the server cache only on a configured server, with no eyebrow", async () => {
    meta.mockResolvedValue({ version: "1", mode: "configured" });
    renderAt("ml-repo");
    const summary = await screen.findByText("Server cache");
    const details = summary.closest("details.cache-details") as HTMLElement;
    expect(await within(details).findByRole("button", { name: "Rebuild" })).toBeTruthy();
    expect(within(details).getByText(/drift 0/)).toBeTruthy();
    expect(details.querySelector(".eyebrow")).toBeNull();
  });

  it("hides the server cache on a standalone server", async () => {
    renderAt("ml-repo");
    await screen.findByRole("link", { name: "clf" });
    await settled();
    expect(screen.queryByText("Server cache")).toBeNull();
  });

  it("hides the server cache when its status is refused", async () => {
    meta.mockResolvedValue({ version: "1", mode: "configured" });
    cacheStatus.mockRejectedValue(Object.assign(new Error("Forbidden"), { status: 403 }));
    renderAt("ml-repo");
    await screen.findByRole("link", { name: "clf" });
    await vi.waitFor(() => expect(cacheStatus).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("Server cache")).toBeNull();
  });

  it("explains how to make an app in an empty git workspace", async () => {
    apps.mockResolvedValue([]);
    renderAt("ml-repo");
    const empty = await screen.findByText(/No vmn apps in ml-repo yet/);
    expect(empty.textContent).toBe(
      "No vmn apps in ml-repo yet. Run vmn stamp -r patch <app> or vmn-exp run <app> -- <cmd> in the checkout.",
    );
  });

  it("says a store workspace has no runs yet", async () => {
    apps.mockResolvedValue([]);
    renderAt("shared");
    expect(await screen.findByText("No runs in this store yet.")).toBeTruthy();
  });
});
