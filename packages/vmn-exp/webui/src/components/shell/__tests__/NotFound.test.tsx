import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";
import type { Meta, Workspace } from "../../../types";

const meta = vi.fn<() => Promise<Meta>>();
const workspaces = vi.fn<() => Promise<Workspace[]>>();
const apps = vi.fn();
const facets = vi.fn();
vi.mock("../../../api", () => ({
  appName: (tag: string) => tag.replaceAll("-", "/"),
  api: {
    meta: () => meta(), workspaces: () => workspaces(),
    apps: (ws: string) => apps(ws), facets: (ws: string, app: string) => facets(ws, app),
  },
}));

import NotFound from "../NotFound";
import { ShellOverrideProvider, useShellOverride } from "../../../shell/shellOverride";
import type { NotFoundProps } from "../../../shell/contracts";

const AUTH = { enabled: true, token: true, oidc: false, login_url: null };

function Probe() {
  return <span data-testid="override">{useShellOverride() ?? "none"}</span>;
}

function renderNotFound(props: NotFoundProps) {
  return renderWithClient(
    <MemoryRouter>
      <ShellOverrideProvider>
        <NotFound {...props} />
        <Probe />
      </ShellOverrideProvider>
    </MemoryRouter>,
  );
}

const linkNames = () => screen.queryAllByRole("link").map((a) => a.textContent);

beforeEach(() => {
  vi.clearAllMocks();
  meta.mockResolvedValue({ version: "0.10.2" });
  workspaces.mockResolvedValue([{ name: "ml-repo", kind: "git", path: "/srv/ml-repo" }]);
  apps.mockResolvedValue([]);
  facets.mockResolvedValue({ branches: [], metric_keys: [], param_keys: [], total: 53 });
});

describe("NotFound", () => {
  it("focuses its heading on mount and retitles the shell", async () => {
    renderNotFound({ kind: "route", pathname: "/nowhere" });
    const h1 = screen.getByRole("heading", { level: 1, name: "No page at this address" });
    expect(h1).toHaveFocus();
    expect(h1.tabIndex).toBe(-1);
    expect(screen.getByTestId("override").textContent).toBe("not-found");
  });

  it("renders the first action as the primary one", async () => {
    renderNotFound({ kind: "route", pathname: "/ws/ml-repo/bogus" });
    const open = await screen.findByRole("link", { name: "Open ml-repo" });
    const all = screen.getByRole("link", { name: "All workspaces" });
    expect(all).toHaveClass("primary");
    expect(open).not.toHaveClass("primary");
    expect(all.compareDocumentPosition(open) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders no eyebrow", () => {
    const { container } = renderNotFound({ kind: "route", pathname: "/x" });
    expect(container.querySelector(".eyebrow")).toBeNull();
  });

  it("offers to attach a checkout with auth off on a writable server", async () => {
    renderNotFound({ kind: "workspace", ws: "x" });
    const attach = await screen.findByRole("link", { name: "Attach a checkout as x" });
    expect(attach.getAttribute("href")).toBe("/?add=1&name=x");
    expect(screen.getByText("vmn-exp ui --repo <path>")).toBeInTheDocument();
  });

  it("hides attach on a read-only server", async () => {
    meta.mockResolvedValue({ version: "1", read_only: true });
    renderNotFound({ kind: "workspace", ws: "x" });
    await waitFor(() => expect(meta).toHaveBeenCalled());
    await screen.findByText(/Workspaces on this server/);
    expect(linkNames()).not.toContain("Attach a checkout as x");
  });

  it("hides attach from a principal without the global admin role", async () => {
    meta.mockResolvedValue({ version: "1", auth: AUTH, role: null });
    workspaces.mockResolvedValue([{ name: "ml-repo", kind: "git", role: "admin" }]);
    renderNotFound({ kind: "workspace", ws: "x" });
    await screen.findByText(/Workspaces on this server/);
    expect(linkNames()).not.toContain("Attach a checkout as x");
  });

  it("offers attach to a global admin", async () => {
    meta.mockResolvedValue({ version: "1", auth: AUTH, role: "admin" });
    renderNotFound({ kind: "workspace", ws: "x" });
    expect(await screen.findByRole("link", { name: "Attach a checkout as x" })).toBeInTheDocument();
  });

  it("suggests an app and never offers to create one", async () => {
    apps.mockResolvedValue([{ name: "ml_app", experiments: 3, versions: 1 }]);
    renderNotFound({ kind: "app", ws: "ml-repo", appTag: "ml_ap" });
    const open = await screen.findByRole("link", { name: "Open ml_app" });
    expect(open.getAttribute("href")).toBe("/ws/ml-repo/app/ml_app");
    expect(document.body.textContent).not.toMatch(/create|new run/i);
    expect(screen.queryByRole("button", { name: /new|create/i })).toBeNull();
  });

  it("gives an @N ref the app's range from its facets", async () => {
    renderNotFound({ kind: "run", ws: "ml-repo", appTag: "ml_app", runRef: "@540" });
    expect(await screen.findByText("ml_app has 53 runs (@1–@53).")).toBeInTheDocument();
    expect(facets).toHaveBeenCalledWith("ml-repo", "ml_app");
  });

  it("asks for no facets or apps it does not show", async () => {
    renderNotFound({ kind: "model", ws: "ml-repo", name: "resnet" });
    await waitFor(() => expect(meta).toHaveBeenCalled());
    expect(facets).not.toHaveBeenCalled();
    expect(apps).not.toHaveBeenCalled();
  });

  it("shows the CLI line with a copy button", () => {
    renderNotFound({ kind: "model", ws: "ml-repo", name: "resnet" });
    expect(screen.getByText("vmn-exp model list")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy command" })).toBeInTheDocument();
  });

  it("names the store a git-only page cannot use", async () => {
    workspaces.mockResolvedValue([{ name: "team", kind: "store", store: "s3://team-exp/ml" }]);
    renderNotFound({ kind: "needs-git", ws: "team", appTag: "ml_app", page: "actions" });
    expect(screen.getByRole("heading", { name: "Actions need a git workspace" })).toBeInTheDocument();
    expect(await screen.findByText("s3://team-exp/ml")).toBeInTheDocument();
  });
});
