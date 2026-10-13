import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import LeaderboardFilter from "../LeaderboardFilter";

const box = () => screen.getByLabelText("Filter query") as HTMLInputElement;
const tokens = () => within(screen.getByRole("list", { name: "Active filters" }))
  .queryAllByRole("listitem").map((li) => li.getAttribute("data-token"));
const removeButton = (text: string) => screen.getByRole("button", { name: `Remove filter ${text}` });
const settle = () => act(() => { vi.advanceTimersByTime(400); });
const typeAndEnter = (text: string) => {
  fireEvent.change(box(), { target: { value: text } });
  fireEvent.keyDown(box(), { key: "Enter" });
};

describe("LeaderboardFilter: one filter grammar", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("clicking a status shortcut adds its clause as a token and reports ?status=", () => {
    const onStatusChange = vi.fn();
    render(<LeaderboardFilter onStatusChange={onStatusChange} />);
    fireEvent.click(screen.getByRole("button", { name: "failed" }));
    expect(tokens()).toEqual(['status = "failed"']);
    expect(onStatusChange).toHaveBeenLastCalledWith("failed");
  });

  it("removing the token clears the filter and its shortcut", () => {
    const onStatusChange = vi.fn();
    render(<LeaderboardFilter onStatusChange={onStatusChange} />);
    fireEvent.click(screen.getByRole("button", { name: "failed" }));
    fireEvent.click(removeButton('status = "failed"'));
    expect(tokens()).toEqual([]);
    expect(onStatusChange).toHaveBeenLastCalledWith("");
    expect(screen.getByRole("button", { name: "failed" })).toHaveAttribute("aria-pressed", "false");
  });

  it("a hand-typed clause becomes the same token as its shortcut", () => {
    const onStatusChange = vi.fn();
    const onQueryChange = vi.fn();
    render(<LeaderboardFilter onStatusChange={onStatusChange} onQueryChange={onQueryChange} />);
    typeAndEnter("status = 'failed'");
    expect(tokens()).toEqual(['status = "failed"']);
    expect(box()).toHaveValue("");
    expect(onStatusChange).toHaveBeenLastCalledWith("failed");
    expect(screen.getByRole("button", { name: "failed" })).toHaveAttribute("aria-pressed", "true");
    settle();
    expect(onQueryChange).toHaveBeenLastCalledWith("");
  });

  it("commits typed query clauses as tokens reported in ?q=", () => {
    const onQueryChange = vi.fn();
    render(<LeaderboardFilter onQueryChange={onQueryChange} />);
    typeAndEnter("metrics.loss < 0.5 and params.lr = 0.1");
    expect(tokens()).toEqual(["metrics.loss < 0.5", "params.lr = 0.1"]);
    expect(onQueryChange).toHaveBeenLastCalledWith("metrics.loss < 0.5 and params.lr = 0.1");
    fireEvent.click(removeButton("metrics.loss < 0.5"));
    expect(onQueryChange).toHaveBeenLastCalledWith("params.lr = 0.1");
  });

  it("free text becomes a text ~ token reported as the search", () => {
    const onSearchChange = vi.fn();
    render(<LeaderboardFilter onSearchChange={onSearchChange} />);
    typeAndEnter("batch");
    expect(tokens()).toEqual(['text ~ "batch"']);
    expect(onSearchChange).toHaveBeenLastCalledWith("batch");
  });

  it("the branch and archived shortcuts write tokens too", () => {
    const onBranchChange = vi.fn();
    const onArchivedChange = vi.fn();
    const { rerender } = render(
      <LeaderboardFilter branches={["main"]} onBranchChange={onBranchChange} onArchivedChange={onArchivedChange} />,
    );
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "main" } });
    expect(tokens()).toEqual(['branch = "main"']);
    expect(onBranchChange).toHaveBeenLastCalledWith("main");
    rerender(
      <LeaderboardFilter archived branches={["main"]} onBranchChange={onBranchChange} onArchivedChange={onArchivedChange} />,
    );
    expect(tokens()).toEqual(['branch = "main"', "archived"]);
    fireEvent.click(removeButton("archived"));
    expect(onArchivedChange).toHaveBeenLastCalledWith(false);
  });

  it("shows the URL's filters as tokens", () => {
    render(<LeaderboardFilter initial={{ status: "running", query: "metrics.loss < 1", branch: "dev", search: "bat" }} />);
    expect(tokens()).toEqual(['status = "running"', 'branch = "dev"', 'text ~ "bat"', "metrics.loss < 1"]);
    expect(box()).toHaveValue("");
  });

  it("Backspace in an empty box removes the last token", () => {
    const onQueryChange = vi.fn();
    render(<LeaderboardFilter initial={{ query: "a = 1 and b = 2" }} onQueryChange={onQueryChange} />);
    fireEvent.keyDown(box(), { key: "Backspace" });
    expect(tokens()).toEqual(["a = 1"]);
    expect(onQueryChange).toHaveBeenLastCalledWith("a = 1");
  });

  it("similar mode keeps the other tokens, the toggle sitting inside the box", () => {
    const onSimilarChange = vi.fn();
    const onStatusChange = vi.fn();
    render(<LeaderboardFilter onSimilarChange={onSimilarChange} onStatusChange={onStatusChange} />);
    fireEvent.click(screen.getByRole("button", { name: "failed" }));
    const toggle = screen.getByRole("button", { name: /^similar$/i });
    expect(toggle.closest(".query-bar-box")).toContainElement(box());
    fireEvent.click(toggle);
    fireEvent.change(box(), { target: { value: "focal loss" } });
    settle();
    expect(onSimilarChange).toHaveBeenLastCalledWith("focal loss");
    expect(tokens()).toEqual(['status = "failed"']);
    expect(onStatusChange).toHaveBeenLastCalledWith("failed");
  });
});
