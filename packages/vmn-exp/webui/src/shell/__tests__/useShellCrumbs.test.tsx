import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient } from "../../queryClient";
import type { AppStatus, RouteId, ShellContext } from "../contracts";

const appStatus = vi.fn<(ws: string, tag: string) => Promise<AppStatus>>();
vi.mock("../../api", () => ({ api: {} }));
vi.mock("../../apiShell", () => ({
  apiShell: { appStatus: (ws: string, tag: string) => appStatus(ws, tag) },
}));

import { runKey } from "../../queries";
import { useShellCrumbs } from "../useShellCrumbs";

const last = <T,>(xs: T[]) => xs[xs.length - 1];
const status = (stuck: number): AppStatus => ({
  total: 3, counts: { created: 0, running: 0, stuck, succeeded: 3 - stuck, failed: 0 },
  failed_recent: 0, recent_sec: 86400, rollup: stuck ? "stuck" : null,
});

function fakeCtx(routeId: RouteId, extra: Partial<ShellContext> = {}): ShellContext {
  return {
    ws: "ml-repo", workspace: { name: "ml-repo", kind: "git" }, workspaces: [], isGit: true,
    metaStatus: "ok", metaError: false, authEnabled: false, role: null,
    readOnly: false, readOnlyReason: null, canAdmin: true,
    routeId, params: { ws: "ml-repo" }, search: new URLSearchParams(), pathname: "/",
    wsFromUrl: true, override: null, ...extra,
  };
}
const appCtx = (routeId: RouteId, extra: Partial<ShellContext> = {}) => fakeCtx(routeId, {
  appTag: "ml_app", app: "ml_app", appBase: "/ws/ml-repo/app/ml_app", ...extra,
});

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) =>
  <QueryClientProvider client={client}>{children}</QueryClientProvider>;
const shell = (ctx: ShellContext) => renderHook(() => useShellCrumbs(ctx), { wrapper });

describe("useShellCrumbs", () => {
  beforeEach(() => {
    client = createQueryClient();
    appStatus.mockReset();
    appStatus.mockResolvedValue(status(0));
  });

  it("an override replaces the route's crumbs, commands and title", () => {
    const { result } = shell(appCtx("run", { override: "not-found", params: { verstr: "@99" } }));
    expect(result.current.crumbs.map((c) => c.label)).toEqual(["not found"]);
    expect(result.current.cli).toEqual([]);
    expect(result.current.title).toBe("not found — vmn-exp");
  });

  it("reads a report's title from the cache", () => {
    client.setQueryData(["report", "ml-repo", "r1"], { rid: "r1", title: "Q3 review", rev: 1 });
    const { result } = shell(fakeCtx("report", { params: { ws: "ml-repo", rid: "r1" } }));
    expect(result.current.crumbs.map((c) => c.label)).toEqual(["reports", "Q3 review"]);
    expect(result.current.title).toBe("Q3 review · reports — vmn-exp");
  });

  it("labels a run from the cache and copies its verstr", () => {
    client.setQueryData(runKey("ml-repo", "ml_app", "@54"), {
      metadata: { verstr: "0.4.1-dev.abc" }, idx: 54, name: "lr",
    });
    const { result } = shell(appCtx("run", { params: { ws: "ml-repo", app: "ml_app", verstr: "@54" } }));
    expect(last(result.current.crumbs)!.label).toBe("@54 lr");
    expect(result.current.cli[0].command).toBe("vmn-exp show ml_app -v 0.4.1-dev.abc");
    expect(result.current.title).toBe("@54 lr · ml_app — vmn-exp");
  });

  it("prefixes the stuck count on app routes", async () => {
    appStatus.mockResolvedValue(status(2));
    const { result } = shell(appCtx("experiments"));
    await waitFor(() => expect(result.current.title).toBe("(2 stuck) ml_app experiments · ml-repo — vmn-exp"));
    expect(appStatus).toHaveBeenCalledWith("ml-repo", "ml_app");
  });

  it("adds --store for a store workspace", () => {
    const { result } = shell(appCtx("experiments", {
      workspace: { name: "team", kind: "store", store: "s3://team-exp/ml" }, isGit: false,
    }));
    expect(result.current.cli[0].command).toBe("vmn-exp list ml_app --store s3://team-exp/ml");
  });
});
