import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { meta: vi.fn(), workspaces: vi.fn(), action: vi.fn(), job: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (name: string) => name.replaceAll("/", "-"),
}));

import { api } from "../../api";
import { vmnCommand, vmnExpCommand } from "../../shell/cliCommands";
import RunHeaderActions from "../RunHeaderActions";

const mocked = api as unknown as Record<"meta" | "workspaces" | "action" | "job", ReturnType<typeof vi.fn>>;
const V = "0.0.1-dev.a+x";
const writeText = vi.fn();

function setup(opts: { readOnly?: boolean; store?: boolean; command?: string[] | null } = {}) {
  mocked.meta.mockResolvedValue({ version: "1", read_only: !!opts.readOnly });
  mocked.workspaces.mockResolvedValue([
    opts.store ? { name: "test", kind: "store", store: "s3://b/p" } : { name: "test", kind: "git", path: "/r" },
  ]);
  return renderWithClient(
    <MemoryRouter>
      <RunHeaderActions ws="test" app="my-app" verstr={V}
        command={opts.command === undefined ? ["python", "train.py"] : opts.command} />
    </MemoryRouter>,
  );
}

const trigger = () => screen.getByRole("button", { name: /Reproduce/ });
const openMenu = () => { fireEvent.click(trigger()); return screen.getByRole("menu"); };
const settle = () => act(() => new Promise((r) => setTimeout(r, 20)));
const item = (name: RegExp) => screen.getByRole("menuitem", { name });

beforeEach(() => {
  vi.clearAllMocks();
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
});

// Let the meta/workspaces queries settle inside act.
afterEach(() => settle());

describe("Reproduce menu a11y", () => {
  it("is a menu button that focuses its first item and closes on Escape, focus back", async () => {
    setup();
    expect(trigger()).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    const menu = openMenu();
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    const items = screen.getAllByRole("menuitem");
    expect(items[0]).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(items[1]).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger()).toHaveFocus();
  });

  it("explains each command in one line", () => {
    setup();
    openMenu();
    expect(item(/vmn-exp restore/)).toHaveTextContent("into this checkout (saves dirty work first)");
    expect(item(/vmn-exp rerun/)).toHaveTextContent("in a throwaway worktree");
    expect(item(/vmn-exp export/)).toHaveTextContent("a bundle for a container");
  });
});

describe("Reproduce copies the CLI commands", () => {
  it("copies vmn-exp restore and announces it", async () => {
    setup();
    openMenu();
    fireEvent.click(item(/vmn-exp restore/));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(vmnExpCommand(["restore", "my/app", "-v", V])));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("copied"));
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger()).toHaveFocus();
  });

  it("copies rerun and export the way the CLI spells them", async () => {
    setup();
    openMenu();
    fireEvent.click(item(/vmn-exp rerun/));
    await waitFor(() => expect(writeText).toHaveBeenLastCalledWith(vmnExpCommand(["rerun", "my/app", "-v", V])));
    openMenu();
    fireEvent.click(item(/vmn-exp export/));
    await waitFor(() => expect(writeText).toHaveBeenLastCalledWith(vmnExpCommand(["export", "my/app", "-v", V])));
  });

  it("adds --store in a store workspace", async () => {
    setup({ store: true });
    await settle();
    openMenu();
    expect(item(/vmn-exp restore/)).toHaveTextContent("--store");
    fireEvent.click(item(/vmn-exp restore/));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(
      vmnExpCommand(["restore", "my/app", "-v", V], "s3://b/p"),
    ));
  });

  it("offers rerun only for a run that recorded a command, with a link to its reruns", () => {
    setup({ command: null });
    openMenu();
    expect(screen.queryByRole("menuitem", { name: /vmn-exp rerun/ })).toBeNull();
  });

  it("links to the run's reruns when it has a command", () => {
    setup();
    openMenu();
    expect(screen.getByRole("menuitem", { name: "reruns →" })).toHaveAttribute(
      "href", `/ws/test/app/my-app?q=${encodeURIComponent(`rerun_of = "${V}"`)}`,
    );
  });
});

describe("Copy link", () => {
  it("copies the canonical run URL and announces it", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(
      `${window.location.origin}/ws/test/app/my-app/run/${encodeURIComponent(V)}`,
    ));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("copied"));
  });
});

describe("vmn goto through the job runner", () => {
  it("asks first, showing the command, then runs the goto job", async () => {
    mocked.action.mockResolvedValue({ id: "j1", command: [], status: "running", exit_code: null, log: "" });
    setup();
    await settle();
    openMenu();
    fireEvent.click(item(/vmn goto/));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(vmnCommand(["goto", "-v", V, "my/app"]));
    expect(mocked.action).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Run goto" }));
    await waitFor(() => expect(mocked.action).toHaveBeenCalledWith("test", "my-app", "goto", { verstr: V }));
    expect(await screen.findByText(/job running/)).toBeInTheDocument();
  });

  it("Cancel runs nothing and gives focus back to Reproduce", async () => {
    setup();
    await settle();
    openMenu();
    fireEvent.click(item(/vmn goto/));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocked.action).not.toHaveBeenCalled();
    expect(trigger()).toHaveFocus();
  });

  it("is hidden on a read-only server", async () => {
    setup({ readOnly: true });
    await settle();
    openMenu();
    expect(screen.queryByRole("menuitem", { name: /vmn goto/ })).toBeNull();
  });

  it("is hidden in a store workspace", async () => {
    setup({ store: true });
    await settle();
    openMenu();
    expect(screen.queryByRole("menuitem", { name: /vmn goto/ })).toBeNull();
  });
});
