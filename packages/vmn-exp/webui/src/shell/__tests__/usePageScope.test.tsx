import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { createQueryClient } from "../../queryClient";
import type { Meta, Workspace } from "../../types";

const meta = vi.fn<() => Promise<Meta>>();
const workspaces = vi.fn<() => Promise<Workspace[]>>();
vi.mock("../../api", () => ({ api: { meta: () => meta(), workspaces: () => workspaces() } }));

import { usePageScope } from "../usePageScope";

const AUTH = { enabled: true, token: true, oidc: false, api_tokens: false, login_url: null };
const fail = (status?: number) =>
  Promise.reject(Object.assign(new Error("x"), status ? { status } : {}));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

async function scopeFor(ws?: string) {
  const { result } = renderHook(() => usePageScope(ws), { wrapper });
  await waitFor(() => expect(result.current.metaStatus).not.toBe("loading"));
  await waitFor(() => expect(workspaces).toHaveBeenCalled());
  await waitFor(() => expect(result.current.workspaces.length).toBeGreaterThan(0));
  return result.current;
}

describe("usePageScope", () => {
  beforeEach(() => {
    meta.mockReset();
    workspaces.mockReset();
    workspaces.mockResolvedValue([{ name: "ml-repo", kind: "git", path: "/srv/ml-repo" }]);
  });

  it("is writable with auth off, and everyone may administer", async () => {
    meta.mockResolvedValue({ version: "0.10.2" });
    const s = await scopeFor("ml-repo");
    expect(s).toMatchObject({
      ws: "ml-repo", isGit: true, metaStatus: "ok", metaError: false, authEnabled: false,
      role: null, readOnly: false, readOnlyReason: null, canAdmin: true,
    });
    expect(s.workspace?.name).toBe("ml-repo");
  });

  it("rule 1: --read-only wins over every other reason", async () => {
    meta.mockResolvedValue({ version: "1", read_only: true, auth: AUTH, role: "viewer" });
    workspaces.mockResolvedValue([{ name: "ml-repo", kind: "git", role: "viewer" }]);
    const s = await scopeFor("ml-repo");
    expect(s.readOnly).toBe(true);
    expect(s.readOnlyReason).toBe("Started with --read-only: actions and edits are off");
  });

  it("rule 2: a viewer in the workspace", async () => {
    meta.mockResolvedValue({ version: "1", auth: AUTH, role: null });
    workspaces.mockResolvedValue([{ name: "ml-repo", kind: "git", role: "viewer" }]);
    const s = await scopeFor("ml-repo");
    expect(s.role).toBe("viewer");
    expect(s.readOnlyReason).toBe("Your role in ml-repo is viewer");
  });

  it("rule 3: no role in the workspace", async () => {
    meta.mockResolvedValue({ version: "1", auth: AUTH, role: null });
    workspaces.mockResolvedValue([{ name: "ml-repo", kind: "git", role: null }]);
    const s = await scopeFor("ml-repo");
    expect(s.readOnly).toBe(true);
    expect(s.readOnlyReason).toBe("You have no role in ml-repo");
  });

  it("rule 4: a probed store without edit", async () => {
    meta.mockResolvedValue({ version: "1" });
    workspaces.mockResolvedValue([{ name: "team", kind: "store", capabilities: ["read"] }]);
    const s = await scopeFor("team");
    expect(s.isGit).toBe(false);
    expect(s.readOnlyReason).toBe("This store gives no edit access");
  });

  it("an unprobed store (no capabilities) is not read-only", async () => {
    meta.mockResolvedValue({ version: "1" });
    workspaces.mockResolvedValue([{ name: "team", kind: "store" }]);
    const s = await scopeFor("team");
    expect(s.readOnly).toBe(false);
    expect(s.readOnlyReason).toBeNull();
  });

  it("a per-workspace admin is not a global admin", async () => {
    meta.mockResolvedValue({ version: "1", auth: AUTH, role: null });
    workspaces.mockResolvedValue([{ name: "ml-repo", kind: "git", role: "admin" }]);
    const s = await scopeFor("ml-repo");
    expect(s.role).toBe("admin");
    expect(s.readOnly).toBe(false);
    expect(s.canAdmin).toBe(false);
  });

  it("a global admin may administer", async () => {
    meta.mockResolvedValue({ version: "1", auth: AUTH, role: "admin" });
    expect((await scopeFor()).canAdmin).toBe(true);
  });

  it.each([
    [401, "unauthorized"],
    [403, "forbidden"],
    [undefined, "unreachable"],
  ])("a meta failure with status %s is %s", async (status, expected) => {
    meta.mockImplementation(() => fail(status));
    const s = await scopeFor();
    expect(s.metaStatus).toBe(expected);
    expect(s.metaError).toBe(expected === "unreachable");
  });

  it("is loading and writable before meta answers", () => {
    meta.mockImplementation(() => new Promise(() => {}));
    workspaces.mockImplementation(() => new Promise(() => {}));
    const { result } = renderHook(() => usePageScope("ml-repo"), { wrapper });
    expect(result.current).toMatchObject({
      metaStatus: "loading", readOnly: false, role: null, isGit: true, workspaces: [],
    });
  });
});
