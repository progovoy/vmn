import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import type { GitContext } from "../../../shell/contracts";
import { ctxOf, ML_REPO, renderShell, TEAM } from "./topbarFixtures";

const gitContext = vi.fn<(ws: string) => Promise<GitContext>>();
vi.mock("../../../apiShell", () => ({ apiShell: { gitContext: (ws: string) => gitContext(ws) } }));

import ContextRoot from "../ContextRoot";

const GIT: GitContext = {
  branch: "main", detached: false, head: "e71c74d0".padEnd(40, "0"), head_short: "e71c74d",
  dirty: false, store: ".vmn/store",
};

const renderGit = () =>
  renderShell(<ContextRoot ctx={ctxOf({ ws: "ml-repo", workspace: ML_REPO })} />).container;
const flat = (el: HTMLElement) => el.textContent!.replace(/\s+/g, " ").trim();

describe("ContextRoot", () => {
  beforeEach(() => { gitContext.mockReset(); });

  it("on a clean branch: workspace link, branch @ HEAD and the store", async () => {
    gitContext.mockResolvedValue(GIT);
    const c = renderGit();
    expect(screen.getByRole("link", { name: "ml-repo" })).toHaveAttribute("href", "/ws/ml-repo");
    await screen.findByText("main @ e71c74d");
    expect(flat(c)).toBe("ml-repo main @ e71c74d · .vmn/store");
    expect(gitContext).toHaveBeenCalledWith("ml-repo");
    expect(c.querySelector(".ctx-dirty")).toBeNull();
  });

  it("marks a dirty tree with a badge that says how to save it", async () => {
    gitContext.mockResolvedValue({ ...GIT, dirty: true });
    const c = renderGit();
    const badge = await screen.findByText("dirty");
    expect(badge).toHaveClass("ctx-dirty");
    expect(badge).toHaveAttribute(
      "title", "uncommitted changes to tracked files. vmn snapshot create <app> saves them",
    );
    expect(flat(c)).toBe("ml-repo main @ e71c74d dirty · .vmn/store");
  });

  it("names the app in the dirty hint when one is in context", async () => {
    gitContext.mockResolvedValue({ ...GIT, dirty: true });
    renderShell(<ContextRoot ctx={ctxOf({ ws: "ml-repo", workspace: ML_REPO, app: "root/svc" })} />);
    expect(await screen.findByText("dirty")).toHaveAttribute(
      "title", "uncommitted changes to tracked files. vmn snapshot create root/svc saves them",
    );
  });

  it("on a detached HEAD", async () => {
    gitContext.mockResolvedValue({ ...GIT, branch: null, detached: true });
    const c = renderGit();
    await screen.findByText("detached @ e71c74d");
    expect(flat(c)).toBe("ml-repo detached @ e71c74d · .vmn/store");
  });

  it("before the first commit", async () => {
    gitContext.mockResolvedValue({ ...GIT, head: null, head_short: null });
    const c = renderGit();
    await screen.findByText("main @ (no commits)");
    expect(flat(c)).toBe("ml-repo main @ (no commits) · .vmn/store");
  });

  it("drops the git segment silently while loading or when git failed", async () => {
    gitContext.mockResolvedValue({
      branch: null, detached: false, head: null, head_short: null, dirty: null,
      store: ".vmn/store", error: "fatal: not a git repository",
    });
    const c = renderGit();
    expect(flat(c)).toBe("ml-repo");
    await waitFor(() => expect(gitContext).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(flat(c)).toBe("ml-repo");
  });

  it("drops the git segment when the request fails", async () => {
    gitContext.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));
    const c = renderGit();
    await waitFor(() => expect(gitContext).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(flat(c)).toBe("ml-repo");
  });

  it("shows a store workspace's URI middle-truncated, in full in the title, with no git request", async () => {
    const c = renderShell(<ContextRoot ctx={ctxOf({ ws: "team", workspace: TEAM, isGit: false })} />).container;
    const store = c.querySelector(".ctx-store")!;
    expect(store).toHaveAttribute("title", TEAM.store);
    expect(store.textContent).toMatch(/^store · s3:\/\/team-exp.*…/);
    expect(store.textContent!.endsWith(TEAM.store!.slice(-8))).toBe(true);
    expect(store.textContent!.length).toBeLessThan(`store · ${TEAM.store}`.length);
    expect(screen.getByRole("link", { name: "team" })).toHaveAttribute("href", "/ws/team");
    await new Promise((r) => setTimeout(r, 0));
    expect(gitContext).not.toHaveBeenCalled();
  });

  it("shows a short store URI whole", () => {
    const ws = { ...TEAM, store: "s3://team-exp/ml" };
    const c = renderShell(<ContextRoot ctx={ctxOf({ ws: "team", workspace: ws, isGit: false })} />).container;
    expect(flat(c)).toBe("team store · s3://team-exp/ml");
  });

  it("asks git nothing while the workspace is unknown", async () => {
    renderShell(<ContextRoot ctx={ctxOf({ ws: "ml-repo" })} />);
    await new Promise((r) => setTimeout(r, 0));
    expect(gitContext).not.toHaveBeenCalled();
  });

  it("renders nothing without a workspace", () => {
    const c = renderShell(<ContextRoot ctx={ctxOf({})} />).container;
    expect(c.textContent).toBe("");
  });
});
