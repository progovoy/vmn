/** Plan 28 P4: the app's team views sit above "my views", read-only; an
 *  editor saves the current view as a team view. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import SavedViews from "../SavedViews";
import { saveView } from "../../util/savedViews";

beforeEach(() => localStorage.clear());

const open = () => fireEvent.click(screen.getByRole("button", { name: /^views/i }));
const team = [
  { name: "health", search: "?show=t%3Ahealth", default: true },
  { name: "failed", search: "?status=failed" },
];

describe("SavedViews team views", () => {
  it("lists team views above my views, without delete buttons", () => {
    saveView("w", "a", "mine", "?sort=loss");
    render(<SavedViews ws="w" app="a" search="" onApply={() => {}} team={team} />);
    open();
    const items = screen.getAllByRole("menuitem").map((el) => el.textContent);
    expect(items).toEqual(["health", "failed", "mine"]);
    const teamList = screen.getByRole("group", { name: "Team views" });
    expect(within(teamList).queryByRole("button", { name: /delete/i })).toBeNull();
    expect(within(teamList).getByText("default")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete view mine" })).toBeInTheDocument();
  });

  it("applies a team view through onApplyTeam, mine through onApply", () => {
    saveView("w", "a", "mine", "?sort=loss");
    const onApply = vi.fn();
    const onApplyTeam = vi.fn();
    render(<SavedViews ws="w" app="a" search="" onApply={onApply} onApplyTeam={onApplyTeam} team={team} />);
    open();
    fireEvent.click(screen.getByRole("menuitem", { name: "failed" }));
    expect(onApplyTeam).toHaveBeenCalledWith("?status=failed");
    open();
    fireEvent.click(screen.getByRole("menuitem", { name: "mine" }));
    expect(onApply).toHaveBeenCalledWith("?sort=loss");
  });

  it("offers no team save without onSaveTeam", () => {
    render(<SavedViews ws="w" app="a" search="?q=1" onApply={() => {}} team={team} />);
    open();
    expect(screen.queryByRole("button", { name: "Save for team" })).toBeNull();
  });

  it("saves the current view for the team, as the page default when ticked", async () => {
    const onSaveTeam = vi.fn().mockResolvedValue(undefined);
    render(<SavedViews ws="w" app="a" search="?q=1" onApply={() => {}} onSaveTeam={onSaveTeam} />);
    open();
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "shared" } });
    fireEvent.click(screen.getByLabelText("as this page's default"));
    fireEvent.click(screen.getByRole("button", { name: "Save for team" }));
    await waitFor(() => expect(onSaveTeam).toHaveBeenCalledWith("shared", true));
    expect(await screen.findByText("Saved for the team")).toBeInTheDocument();
    expect(screen.getByLabelText("View name")).toHaveValue("");
  });

  it("shows why a team save failed and keeps the name", async () => {
    const onSaveTeam = vi.fn().mockRejectedValue(new Error("ui.views holds at most 20 views"));
    render(<SavedViews ws="w" app="a" search="?q=1" onApply={() => {}} onSaveTeam={onSaveTeam} />);
    open();
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "shared" } });
    fireEvent.click(screen.getByRole("button", { name: "Save for team" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at most 20 views");
    expect(screen.getByLabelText("View name")).toHaveValue("shared");
  });
});
