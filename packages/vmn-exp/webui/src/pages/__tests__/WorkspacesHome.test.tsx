import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";
import type { AppRow, Meta, Workspace } from "../../types";

const meta = vi.fn<() => Promise<Meta>>();
const workspaces = vi.fn<() => Promise<Workspace[]>>();
const apps = vi.fn<(ws: string) => Promise<AppRow[]>>();
vi.mock("../../api", async (orig) => ({
  ...(await orig<typeof import("../../api")>()),
  api: {
    meta: () => meta(),
    workspaces: () => workspaces(),
    apps: (ws: string) => apps(ws),
    addWorkspace: vi.fn(),
  },
}));

import { WorkspacesHome } from "../Dashboard";
import { RETURN_TO_KEY } from "../../shell/contracts";

const TWO: Workspace[] = [
  { name: "ml-repo", kind: "git", path: "/srv/checkouts/ml-repo" },
  { name: "shared", kind: "store", store: "s3://bucket/vmn" },
];
const AUTH = { enabled: true, token: true, oidc: false, login_url: null };

function renderAt(url: string | { pathname: string; state: unknown }) {
  return renderWithClient(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/" element={<WorkspacesHome />} />
        <Route path="/ws/:ws" element={<div>apps page</div>} />
        <Route path="/ws/:ws/app/:app" element={<div>leaderboard page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

const addDetails = () =>
  screen.getByText("Attach or clone a workspace").closest("details") as HTMLDetailsElement;

/** Lets the mocked meta resolve and the page re-render with it. */
async function settled() {
  await vi.waitFor(() => expect(meta).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 0));
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  meta.mockResolvedValue({ version: "0.10.2" });
  workspaces.mockResolvedValue(TWO);
  apps.mockResolvedValue([]);
});

describe("WorkspacesHome", () => {
  it("shows the heading and the fixed sub copy", async () => {
    renderAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: "Workspaces" })).toBeTruthy();
    expect(screen.getByText(
      "A workspace is a git checkout (its own working tree, .vmn/ and lock) or a store URI read through this server.",
    )).toBeTruthy();
  });

  it("renders each tile as an article whose link holds only the name", async () => {
    const { container } = renderAt("/");
    const link = await screen.findByRole("link", { name: "ml-repo" });
    expect(link.getAttribute("href")).toBe("/ws/ml-repo");
    expect(link.querySelector("a, button, input")).toBeNull();
    const tile = link.closest("article.ws-tile") as HTMLElement;
    expect(tile).toBeTruthy();
    expect(within(tile).getByText("git").className).toContain("kind-badge");
    const copy = within(tile).getByRole("button", { name: /copy/i });
    expect(link.contains(copy)).toBe(false);
    expect(within(tile).getByText("/srv/checkouts/ml-repo")).toBeTruthy();
    expect(screen.getByRole("link", { name: "shared" }).closest("article")!.textContent)
      .toContain("store");
    expect(container.querySelector(".status-dot, .rollup-dot")).toBeNull();
    expect(container.querySelector("[onclick], .eyebrow")).toBeNull();
  });

  it("keeps the add form collapsed by default", async () => {
    renderAt("/");
    await screen.findByRole("link", { name: "ml-repo" });
    expect(addDetails().open).toBe(false);
  });

  it("opens the add form on ?add=1, prefilled from ?name=", async () => {
    renderAt("/?add=1&name=new-repo");
    await screen.findByRole("link", { name: "ml-repo" });
    expect(addDetails().open).toBe(true);
    expect((screen.getByLabelText("name") as HTMLInputElement).value).toBe("new-repo");
  });

  it("opens the add form when there are no workspaces, with the empty copy", async () => {
    workspaces.mockResolvedValue([]);
    renderAt("/");
    expect(await screen.findByText(
      "No workspaces yet. Start vmn-exp ui inside a vmn checkout, or attach one below.",
    )).toBeTruthy();
    expect(addDetails().open).toBe(true);
  });

  it("hides the add form from a non-admin when auth is on", async () => {
    meta.mockResolvedValue({ version: "1", auth: AUTH, role: "editor" });
    renderAt("/");
    await screen.findByRole("link", { name: "ml-repo" });
    await settled();
    expect(screen.queryByText("Attach or clone a workspace")).toBeNull();
  });

  it("hides the add form on a read-only server", async () => {
    meta.mockResolvedValue({ version: "1", read_only: true });
    renderAt("/");
    await screen.findByRole("link", { name: "ml-repo" });
    await settled();
    expect(screen.queryByText("Attach or clone a workspace")).toBeNull();
  });

  it("shows the add form to an admin", async () => {
    meta.mockResolvedValue({ version: "1", auth: AUTH, role: "admin" });
    renderAt("/");
    expect(await screen.findByText("Attach or clone a workspace")).toBeTruthy();
  });

  it("opens the only app of the only workspace on first entry", async () => {
    workspaces.mockResolvedValue([TWO[0]]);
    apps.mockResolvedValue([{ name: "clf", experiments: 3, versions: 1 }]);
    renderAt("/");
    expect(await screen.findByText("leaderboard page")).toBeTruthy();
    expect(apps).toHaveBeenCalledWith("ml-repo");
  });

  it("consumes a valid return-to once", async () => {
    sessionStorage.setItem(RETURN_TO_KEY, "/ws/ml-repo");
    renderAt("/");
    expect(await screen.findByText("apps page")).toBeTruthy();
    expect(sessionStorage.getItem(RETURN_TO_KEY)).toBeNull();
  });

  it("stays home on a home link, even with one workspace and one app", async () => {
    workspaces.mockResolvedValue([TWO[0]]);
    apps.mockResolvedValue([{ name: "clf", experiments: 3, versions: 1 }]);
    renderAt({ pathname: "/", state: { home: true } });
    expect(await screen.findByRole("link", { name: "ml-repo" })).toBeTruthy();
    expect(screen.queryByText("leaderboard page")).toBeNull();
  });

  it("shows the page after a return-to that is home itself", async () => {
    sessionStorage.setItem(RETURN_TO_KEY, "/?add=1");
    renderAt("/");
    expect(await screen.findByRole("link", { name: "ml-repo" })).toBeTruthy();
    expect(sessionStorage.getItem(RETURN_TO_KEY)).toBeNull();
  });
});
