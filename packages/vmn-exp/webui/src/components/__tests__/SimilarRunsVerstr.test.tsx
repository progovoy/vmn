import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { SimilarItem } from "../../apiSimilar";
import { SimilarList } from "../SimilarRuns";

function item(verstr: string, extra: Partial<SimilarItem> = {}): SimilarItem {
  return {
    workspace: "test", app: "my/app", verstr, name: null, score: 0.5,
    reasons: [], signals: {}, group_size: 1, goal: null, author: null,
    timestamp: null, status: "succeeded", note: null, intent: null, ...extra,
  };
}

function renderList(items: SimilarItem[]) {
  return render(
    <MemoryRouter>
      <SimilarList items={items} ownApp="my/app" truncated={false} />
    </MemoryRouter>,
  );
}

describe("SimilarList run labels", () => {
  it("shows a named run's verstr next to its name, like the leaderboard", () => {
    renderList([item("0.0.1-dev.twin", { name: "twin" })]);
    const link = screen.getByRole("link", { name: "twin" });
    expect(link).toHaveAttribute("title", "0.0.1-dev.twin");
    const verstr = within(screen.getByRole("listitem")).getByText("0.0.1-dev.twin");
    expect(verstr).toHaveClass("exp-verstr");
    expect(link).not.toContainElement(verstr);
  });

  it("shows another app's named run's verstr too", () => {
    renderList([item("p1", { name: "feat run", app: "root/feat", workspace: "other" })]);
    expect(screen.getByRole("link", { name: "root/feat:feat run" })).toBeInTheDocument();
    expect(screen.getByText("p1")).toHaveClass("exp-verstr");
  });

  it("labels an unnamed run by its verstr once", () => {
    renderList([item("0.0.1-dev.bare")]);
    expect(screen.getByRole("link", { name: "0.0.1-dev.bare" })).toBeInTheDocument();
    expect(screen.getAllByText("0.0.1-dev.bare")).toHaveLength(1);
  });
});
