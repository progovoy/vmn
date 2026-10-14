/** The tray's Tag action: a popover takes `key=value` tags to set and keys
 *  to remove, counts the runs it changes (`dry_run`), then tags each query
 *  group by query and the explicit picks with one action, and refreshes the
 *  board. Esc closes it, Enter applies. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { action: vi.fn(), actionPreview: vi.fn(), job: vi.fn(), experimentsPaged: vi.fn() },
}));

import { api } from "../../api";
import { readPicks, writePicks } from "../../util/runSelection";
import { addQueryGroup } from "../../util/selectionGroups";
import SelectionTrayHost, { useTrayBoard } from "../SelectionTrayHost";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const onArchived = vi.fn();

function Board() {
  useTrayBoard({ total: 50, showUnarchive: false, onSelectAll: () => {}, onArchived });
  return <div>board</div>;
}

function renderTray() {
  writePicks("w", "a", [{ verstr: "x1", job: "J2" }, { verstr: "x2", job: "J3" }]);
  addQueryGroup("w", "a", {
    scope: "J1", q: "", status: "failed", count: 4000, job: "J1", label: "grid", members: [],
  });
  return renderWithClient(
    <MemoryRouter><SelectionTrayHost ws="w" app="a"><Board /></SelectionTrayHost></MemoryRouter>,
  );
}

const tray = () => screen.getByRole("region", { name: "Selection" });
const popover = () => screen.getByRole("dialog", { name: "Tag the selected runs" });
const openTag = () => fireEvent.click(within(tray()).getByRole("button", { name: "Tag" }));
const toSet = () => within(popover()).getByRole("textbox", { name: "Tags to set" });
const toRemove = () => within(popover()).getByRole("textbox", { name: "Tags to remove" });

const EDIT = { set: { stage: "prod", team: "ml" }, remove: ["old"] };
const GROUP_BODY = { scope: "J1", status: "failed", ...EDIT };
const PICKS_BODY = { q: 'verstr in ("x1", "x2")', archived: true, ...EDIT };

beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
  m.actionPreview.mockImplementation((_w: string, _a: string, _act: string, body: { scope?: string }) =>
    Promise.resolve({ count: body.scope ? 3990 : 2, sample: [] }));
  m.action.mockResolvedValue({ id: "j", status: "running", command: [] });
  m.job.mockResolvedValue({ id: "j", status: "succeeded", command: [] });
});

describe("the tray's Tag action", () => {
  it("opens a popover next to Archive", () => {
    renderTray();
    const tag = within(tray()).getByRole("button", { name: "Tag" });
    expect(tag).toHaveAttribute("aria-expanded", "false");
    openTag();
    expect(tag).toHaveAttribute("aria-expanded", "true");
    expect(toSet()).toHaveFocus();
  });

  it("closes on Escape and keeps the selection", () => {
    renderTray();
    openTag();
    fireEvent.keyDown(toSet(), { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Tag the selected runs" })).toBeNull();
    expect(readPicks("w", "a")).toHaveLength(2);
    expect(within(tray()).getByRole("button", { name: "Tag" })).toHaveFocus();
  });

  it("counts the runs on Enter, then tags each group by query and the picks in one action", async () => {
    renderTray();
    openTag();
    fireEvent.change(toSet(), { target: { value: "stage=prod, team=ml" } });
    fireEvent.change(toRemove(), { target: { value: "old" } });
    fireEvent.keyDown(toRemove(), { key: "Enter" });
    const confirm = await screen.findByRole("dialog", { name: "Tag 3,992 runs?" });
    expect(m.actionPreview.mock.calls.map((c) => [c[2], c[3]])).toEqual([
      ["exp_tag", GROUP_BODY], ["exp_tag", PICKS_BODY],
    ]);
    expect(m.action).not.toHaveBeenCalled();
    fireEvent.click(within(confirm).getByRole("button", { name: "Tag" }));
    await waitFor(() => expect(m.action).toHaveBeenCalledTimes(2), { timeout: 4000 });
    expect(m.action.mock.calls.map((c) => [c[2], c[3]])).toEqual([
      ["exp_tag", GROUP_BODY], ["exp_tag", PICKS_BODY],
    ]);
    await waitFor(() => expect(onArchived).toHaveBeenCalledTimes(1), { timeout: 4000 });
    expect(screen.queryByRole("dialog", { name: "Tag the selected runs" })).toBeNull();
    expect(readPicks("w", "a")).toHaveLength(2);
  });

  it("shows an invalid entry inline and asks the server nothing", () => {
    renderTray();
    openTag();
    fireEvent.change(toSet(), { target: { value: "bad key=1" } });
    fireEvent.click(within(popover()).getByRole("button", { name: "Apply" }));
    expect(within(popover()).getByRole("alert")).toHaveTextContent('"bad key=1": use key=value');
    expect(m.actionPreview).not.toHaveBeenCalled();
  });

  it("shows a count that fails inline", async () => {
    m.actionPreview.mockRejectedValue(new Error("boom"));
    renderTray();
    openTag();
    fireEvent.change(toSet(), { target: { value: "stage=prod" } });
    fireEvent.keyDown(toSet(), { key: "Enter" });
    expect(await within(popover()).findByRole("alert")).toHaveTextContent("Could not count the runs: boom");
  });

  it("shows a failed tag job inline and keeps the popover open", async () => {
    m.job.mockResolvedValue({ id: "j", status: "failed", command: [] });
    renderTray();
    openTag();
    fireEvent.change(toSet(), { target: { value: "stage=prod" } });
    fireEvent.keyDown(toSet(), { key: "Enter" });
    fireEvent.click(within(await screen.findByRole("dialog", { name: /^Tag .* runs\?$/ }))
      .getByRole("button", { name: "Tag" }));
    expect(await within(popover()).findByRole("alert", {}, { timeout: 4000 })).toHaveTextContent("tag failed");
    expect(onArchived).not.toHaveBeenCalled();
  });
});
