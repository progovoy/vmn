/** Plan 20 C5: a `?` beside the query bar opens help listing this app's
 *  fields, the operators and three examples built from its facets. */
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import LeaderboardFilter from "../LeaderboardFilter";
import type { QueryHelpData } from "../../util/queryHelp";

const HELP: QueryHelpData = {
  metrics: ["metrics.val_loss"],
  params: ["params.optimizer"],
  tags: ["tags.team"],
  examples: ["metrics.val_loss < 0.45", 'params.optimizer = "adam"', 'status = "failed" and branch = "main"'],
};
const box = () => screen.getByLabelText("Filter query") as HTMLInputElement;
const helpButton = () => screen.getByRole("button", { name: "Query help" });

function open() {
  render(<LeaderboardFilter help={HELP} onSimilarChange={vi.fn()} />);
  fireEvent.click(helpButton());
  return screen.getByRole("dialog", { name: "Query help" });
}

describe("query help (C5)", () => {
  it("is closed until the ? is pressed", () => {
    render(<LeaderboardFilter help={HELP} />);
    expect(helpButton()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("lists the app's fields, the row fields and the operators", () => {
    const dialog = open();
    expect(helpButton()).toHaveAttribute("aria-expanded", "true");
    for (const f of ["metrics.val_loss", "params.optimizer", "tags.team", "status", "branch", "name"]) {
      expect(within(dialog).getByText(f)).toBeInTheDocument();
    }
    for (const op of ["!=", "~", "in (…)", "and", "= null"]) {
      expect(within(dialog).getByText(op)).toBeInTheDocument();
    }
  });

  it("shows the examples built from the facets; picking one puts it in the box", () => {
    const dialog = open();
    const examples = within(dialog).getAllByRole("button").map((b) => b.textContent);
    expect(examples).toEqual(HELP.examples);
    fireEvent.click(within(dialog).getByRole("button", { name: 'params.optimizer = "adam"' }));
    expect(box()).toHaveValue('params.optimizer = "adam"');
    expect(box()).toHaveFocus();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape and returns focus to the ?", () => {
    const dialog = open();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(helpButton()).toHaveFocus();
  });

  it("shares one Tab stop with the similar toggle; the arrows move between them", () => {
    render(<LeaderboardFilter help={HELP} onSimilarChange={vi.fn()} />);
    const similar = screen.getByRole("button", { name: "similar" });
    expect([similar.tabIndex, helpButton().tabIndex]).toEqual([0, -1]);
    similar.focus();
    fireEvent.keyDown(similar, { key: "ArrowRight" });
    expect(helpButton()).toHaveFocus();
    expect([similar.tabIndex, helpButton().tabIndex]).toEqual([-1, 0]);
  });
});
