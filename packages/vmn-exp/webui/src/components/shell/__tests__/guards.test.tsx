import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";
import type { Workspace } from "../../../types";

const workspaces = vi.fn<() => Promise<Workspace[]>>();
const apps = vi.fn();
const appStatus = vi.fn();
vi.mock("../../../api", () => ({
  appName: (tag: string) => tag.replaceAll("-", "/"),
  api: {
    meta: () => Promise.resolve({ version: "1" }),
    workspaces: () => workspaces(),
    apps: (ws: string) => apps(ws),
    facets: () => Promise.reject(new Error("no facets")),
  },
}));
vi.mock("../../../apiShell", () => ({
  apiShell: { appStatus: (ws: string, tag: string) => appStatus(ws, tag) },
}));

import { AppGuard, GitOnly, WorkspaceGuard } from "../guards";

const never = () => new Promise<never>(() => {});
const fail = (status?: number) =>
  Promise.reject(Object.assign(new Error("x"), status ? { status } : {}));
const status = (total: number) => ({
  total, counts: { created: 0, running: 0, stuck: 0, succeeded: total, failed: 0 },
  failed_recent: 0, rollup: null,
});

let mounts = 0;
function Page() {
  useEffect(() => { mounts += 1; }, []);
  return <div data-testid="page">page</div>;
}

function Go({ to }: { to: string }) {
  const navigate = useNavigate();
  return <button onClick={() => navigate(to)}>go</button>;
}

function renderAt(path: string, element: JSX.Element, route = "/ws/:ws/app/:app") {
  return renderWithClient(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path={route} element={element} /></Routes>
      <Go to="/ws/ml-repo/app/eval" />
    </MemoryRouter>,
  );
}

const page = () => screen.queryByTestId("page");
/** Let every mocked read settle and render before asserting the page stayed. */
const settle = () => act(() => new Promise((r) => setTimeout(r, 30)));

beforeEach(() => {
  vi.clearAllMocks();
  mounts = 0;
  workspaces.mockResolvedValue([{ name: "ml-repo", kind: "git", path: "/r" }]);
  apps.mockResolvedValue([{ name: "ml_app", experiments: 1, versions: 0 }]);
  appStatus.mockResolvedValue(status(1));
});

describe("WorkspaceGuard", () => {
  const guarded = <WorkspaceGuard><Page /></WorkspaceGuard>;

  it("renders the page while the workspaces load", () => {
    workspaces.mockReturnValue(never());
    renderAt("/ws/nope/app/x", guarded);
    expect(page()).not.toBeNull();
  });

  it("renders the page when the list fails", async () => {
    workspaces.mockReturnValue(fail(500));
    renderAt("/ws/nope/app/x", guarded);
    await waitFor(() => expect(workspaces).toHaveBeenCalled());
    await settle();
    expect(page()).not.toBeNull();
  });

  it("shows the workspace not-found once the list lacks the name", async () => {
    renderAt("/ws/nope/app/x", guarded);
    expect(await screen.findByRole("heading", { name: "No workspace named nope" })).toBeInTheDocument();
    expect(page()).toBeNull();
  });

  it("renders the page for a known workspace", async () => {
    renderAt("/ws/ml-repo/app/x", guarded);
    await waitFor(() => expect(workspaces).toHaveBeenCalled());
    expect(page()).not.toBeNull();
  });
});

describe("AppGuard", () => {
  const guarded = <AppGuard><Page /></AppGuard>;
  const missing = () => screen.queryByRole("heading", { name: /^No app/ });
  const appNotFound = () =>
    Promise.reject(Object.assign(new Error("x"), { status: 404, body: { detail: "x", code: "app_not_found" } }));

  it("renders the page for a known app with no runs yet", async () => {
    appStatus.mockResolvedValue(status(0));
    renderAt("/ws/ml-repo/app/ml_app", guarded);
    await waitFor(() => expect(appStatus).toHaveBeenCalled());
    await settle();
    expect(page()).not.toBeNull();
  });

  it("never reads the app list: the status answer alone decides", async () => {
    apps.mockResolvedValue([]);
    renderAt("/ws/ml-repo/app/fresh", guarded);
    await waitFor(() => expect(appStatus).toHaveBeenCalled());
    await settle();
    expect(page()).not.toBeNull();
    expect(missing()).toBeNull();
    expect(apps).not.toHaveBeenCalled();
  });

  it("shows the app not-found when the status answers app_not_found", async () => {
    appStatus.mockImplementation(appNotFound);
    renderAt("/ws/ml-repo/app/ml_ap", guarded);
    expect(await screen.findByRole("heading", { name: "No app ml_ap in ml-repo" })).toBeInTheDocument();
    expect(page()).toBeNull();
  });

  it("waits for the status before deciding", async () => {
    appStatus.mockReturnValue(never());
    renderAt("/ws/ml-repo/app/ml_ap", guarded);
    await waitFor(() => expect(appStatus).toHaveBeenCalled());
    await settle();
    expect(page()).not.toBeNull();
  });

  it("shows the not-found for an invalid tag (status 400)", async () => {
    appStatus.mockReturnValue(fail(400));
    renderAt("/ws/ml-repo/app/bad", guarded);
    expect(await screen.findByRole("heading", { name: /^No app/ })).toBeInTheDocument();
  });

  it("keeps the page on a network error", async () => {
    appStatus.mockReturnValue(fail());
    renderAt("/ws/ml-repo/app/ml_ap", guarded);
    await waitFor(() => expect(appStatus).toHaveBeenCalled());
    await settle();
    expect(page()).not.toBeNull();
  });

  it("keeps the page on a 404 without the app_not_found code", async () => {
    appStatus.mockReturnValue(fail(404));
    renderAt("/ws/ml-repo/app/ml_ap", guarded);
    await waitFor(() => expect(appStatus).toHaveBeenCalled());
    await settle();
    expect(page()).not.toBeNull();
  });

  it("keeps the page mounted across a param change", async () => {
    renderAt("/ws/ml-repo/app/ml_app", guarded);
    await waitFor(() => expect(appStatus).toHaveBeenCalled());
    act(() => screen.getByRole("button", { name: "go" }).click());
    await waitFor(() => expect(appStatus).toHaveBeenCalledWith("ml-repo", "eval"));
    expect(page()).not.toBeNull();
    expect(mounts).toBe(1);
  });
});

describe("GitOnly", () => {
  const guarded = <GitOnly page="tree"><Page /></GitOnly>;

  it("renders the page in a git workspace", async () => {
    renderAt("/ws/ml-repo/app/ml_app", guarded);
    await waitFor(() => expect(workspaces).toHaveBeenCalled());
    expect(page()).not.toBeNull();
  });

  it("explains a store workspace has no stamp tree", async () => {
    workspaces.mockResolvedValue([{ name: "team", kind: "store", store: "s3://team-exp/ml" }]);
    renderAt("/ws/team/app/ml_app", guarded);
    expect(await screen.findByRole("heading", { name: "Stamp tree needs a git workspace" }))
      .toBeInTheDocument();
    expect(page()).toBeNull();
  });
});
