import { describe, it, expect } from "vitest";
import { homeRedirect, validReturnTo } from "../homeRedirect";
import type { AppRow, Workspace } from "../../types";

const first = { key: "default", state: null };
const ws = (name: string): Workspace => ({ name, kind: "git", path: `/srv/${name}` });
const app = (name: string): AppRow => ({ name, experiments: 1, versions: 1 });

describe("validReturnTo", () => {
  it("keeps a same-origin path", () => {
    expect(validReturnTo("/ws/w/app/a?q=1")).toBe("/ws/w/app/a?q=1");
  });

  it("refuses a protocol-relative URL, an absolute URL and nothing", () => {
    expect(validReturnTo("//evil.example/x")).toBeNull();
    expect(validReturnTo("https://evil.example/x")).toBeNull();
    expect(validReturnTo("")).toBeNull();
    expect(validReturnTo(null)).toBeNull();
  });
});

describe("homeRedirect", () => {
  it("goes to a valid return-to first, whatever the workspaces", () => {
    expect(homeRedirect({ location: first, returnTo: "/ws/a/app/x", workspaces: undefined }))
      .toEqual({ to: "/ws/a/app/x" });
  });

  it("ignores an invalid return-to", () => {
    expect(homeRedirect({ location: first, returnTo: "//evil", workspaces: [ws("a"), ws("b")] }))
      .toBeNull();
  });

  it("waits for the workspaces when there is no return-to", () => {
    expect(homeRedirect({ location: first, returnTo: null, workspaces: undefined })).toBe("wait");
  });

  it("1 workspace x 1 app opens the app's leaderboard", () => {
    expect(homeRedirect({
      location: first, returnTo: null, workspaces: [ws("w")], apps: [app("root/svc")],
    })).toEqual({ to: "/ws/w/app/root-svc" });
  });

  it("1 workspace waits for its apps", () => {
    expect(homeRedirect({ location: first, returnTo: null, workspaces: [ws("w")] })).toBe("wait");
  });

  it("1 workspace x N apps opens the workspace", () => {
    expect(homeRedirect({
      location: first, returnTo: null, workspaces: [ws("w")], apps: [app("a"), app("b")],
    })).toEqual({ to: "/ws/w" });
  });

  it("N workspaces stay home, whatever their apps", () => {
    expect(homeRedirect({
      location: first, returnTo: null, workspaces: [ws("a"), ws("b")], apps: [app("x")],
    })).toBeNull();
    expect(homeRedirect({ location: first, returnTo: null, workspaces: [] })).toBeNull();
  });

  it("never redirects a home link (state.home)", () => {
    expect(homeRedirect({
      location: { key: "default", state: { home: true } }, returnTo: "/ws/a",
      workspaces: [ws("w")], apps: [app("a")],
    })).toBeNull();
  });

  it("never redirects after the first entry", () => {
    expect(homeRedirect({
      location: { key: "k3x9", state: null }, returnTo: "/ws/a",
      workspaces: [ws("w")], apps: [app("a")],
    })).toBeNull();
  });
});
