/** Plan 22 F9: the phone Group by menu is fixed to the viewport, so it is
 *  told where its trigger's bottom is, when it opens and as the page scrolls. */
import { describe, it, expect, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import GroupByMenu from "../GroupByMenu";
import { LINK_GROUPS } from "../../util/groupBy";

const rect = (bottom: number) => ({ top: bottom - 30, bottom, left: 0, right: 100, width: 100, height: 30, x: 0, y: bottom - 30, toJSON: () => ({}) }) as DOMRect;

function setup() {
  render(
    <GroupByMenu value="parent" links={LINK_GROUPS} fields={[]} onChange={vi.fn()} aggregate="mean" onAggregate={vi.fn()}
      groupSort={null} onGroupSort={vi.fn()} />,
  );
  return screen.getByRole("button", { name: /^group by/i });
}
const top = () => screen.getByRole("menu").style.getPropertyValue("--group-by-top");

describe("the Group by menu's anchor (plan 22 F9)", () => {
  it("opens just under its trigger, wherever the page has scrolled", () => {
    const trigger = setup();
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue(rect(412));
    fireEvent.click(trigger);
    expect(top()).toBe("418px");
  });

  it("follows the trigger as the page scrolls or resizes while open", () => {
    const trigger = setup();
    const at = vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue(rect(200));
    fireEvent.click(trigger);
    at.mockReturnValue(rect(80));
    act(() => { document.dispatchEvent(new Event("scroll")); });
    expect(top()).toBe("86px");
    at.mockReturnValue(rect(120));
    act(() => { window.dispatchEvent(new Event("resize")); });
    expect(top()).toBe("126px");
  });
});
