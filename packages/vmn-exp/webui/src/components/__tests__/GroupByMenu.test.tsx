import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import GroupByMenu from "../GroupByMenu";
import { LINK_GROUPS, groupFields } from "../../util/groupBy";

const fields = groupFields({
  branches: [], metric_keys: [], param_keys: ["lr", "seed"], tag_keys: ["team"],
  param_values: { lr: 4, seed: 21 }, parented: 1, total: 9,
});

function setup(value = "parent", extra: Partial<Parameters<typeof GroupByMenu>[0]> = {}) {
  const onChange = vi.fn();
  const onAggregate = vi.fn();
  render(
    <GroupByMenu
      value={value} links={LINK_GROUPS} fields={fields} onChange={onChange}
      aggregate="mean" onAggregate={onAggregate} {...extra}
    />,
  );
  return { onChange, onAggregate };
}
const trigger = () => screen.getByRole("button", { name: /^group by/i });
const open = () => fireEvent.click(trigger());

describe("GroupByMenu (plan 22 G2, G10)", () => {
  it("names the current grouping on its button", () => {
    setup("rerun_of");
    expect(trigger()).toHaveTextContent("Group by: rerun of");
    expect(trigger()).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("says just Group by while ungrouped, and shows a field as written", () => {
    setup("none");
    expect(trigger()).toHaveTextContent(/^Group by ▾$/);
  });

  it("lists none, then the Links and Fields sections", () => {
    setup();
    open();
    const menu = screen.getByRole("menu", { name: "Group by" });
    const items = within(menu).getAllByRole("menuitemradio").map((i) => i.textContent);
    expect(items).toEqual([
      "none", "parent run", "forked from", "rerun of", "same code",
      "branch", "status", "tags.team", "params.lr",
    ]);
    const links = within(menu).getByRole("group", { name: "Links" });
    expect(within(links).getAllByRole("menuitemradio")).toHaveLength(4);
    const fieldGroup = within(menu).getByRole("group", { name: "Fields" });
    expect(within(fieldGroup).queryByText("params.seed")).toBeNull();
  });

  it("checks the current choice and picks another, closing the menu", () => {
    const { onChange } = setup("parent");
    open();
    expect(screen.getByRole("menuitemradio", { name: "parent run" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemradio", { name: "branch" })).toHaveAttribute("aria-checked", "false");
    fireEvent.click(screen.getByRole("menuitemradio", { name: "tags.team" }));
    expect(onChange).toHaveBeenCalledWith("tags.team");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("keeps a URL group the facets no longer offer, checked", () => {
    setup("params.seed");
    open();
    expect(screen.getByRole("menuitemradio", { name: "params.seed" })).toHaveAttribute("aria-checked", "true");
  });

  it("switches the aggregate (mean pressed by default), staying open", () => {
    const { onAggregate } = setup();
    open();
    const agg = screen.getByRole("group", { name: "Aggregate" });
    const buttons = within(agg).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["mean", "best", "median", "min", "max"]);
    expect(within(agg).getByRole("button", { name: "mean" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(agg).getByRole("button", { name: "best" }));
    expect(onAggregate).toHaveBeenCalledWith("best");
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("offers no aggregate while ungrouped", () => {
    setup("none");
    open();
    expect(screen.queryByRole("group", { name: "Aggregate" })).toBeNull();
  });

  it("closes on Escape", () => {
    setup();
    open();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("moves between choices with the arrow keys", () => {
    setup();
    open();
    const menu = screen.getByRole("menu");
    expect(document.activeElement).toBe(screen.getByRole("menuitemradio", { name: "parent run" }));
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("menuitemradio", { name: "forked from" }));
  });
});
