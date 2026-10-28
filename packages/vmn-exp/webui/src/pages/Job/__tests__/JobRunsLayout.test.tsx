/** Plan 28 N6: an outer run's Runs tab lays its runs out flat (the scoped
 *  board) or as a tree; `layout=` in the URL wins, else the app's last
 *  choice (localStorage). */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../JobRuns", () => ({ default: () => <div>flat board</div> }));
vi.mock("../JobTree", () => ({ default: ({ verstr }: { verstr: string }) => <div>tree of {verstr}</div> }));
vi.mock("../../../shell/useShellData", () => ({ useScopedStatus: () => ({ data: undefined }) }));

import JobRunsTab from "../JobRunsTab";

const JOB = "0.0.2-rc.1";

function Where() {
  return <output data-testid="where">{useLocation().search}</output>;
}

function renderTab(search = "?tab=runs") {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}${search}`]}>
      <JobRunsTab ws="test" app="my-app" verstr={JOB} paused={false} onPaused={() => {}} />
      <Where />
    </MemoryRouter>,
  );
}

const choose = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

beforeEach(() => localStorage.clear());

describe("the Runs tab's layout", () => {
  it("is the tree until the flat board is chosen", () => {
    renderTab();
    expect(screen.getByText(`tree of ${JOB}`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tree" })).toHaveAttribute("aria-pressed", "true");
  });

  it("switches to the flat board, keeping the choice in the URL", () => {
    renderTab();
    choose("Flat");
    expect(screen.getByText("flat board")).toBeInTheDocument();
    expect(new URLSearchParams(screen.getByTestId("where").textContent!).get("layout")).toBe("flat");
  });

  it("remembers the app's last layout", () => {
    const first = renderTab();
    choose("Flat");
    first.unmount();
    renderTab();
    expect(screen.getByText("flat board")).toBeInTheDocument();
  });

  it("follows the URL over the remembered layout", () => {
    const first = renderTab();
    choose("Flat");
    first.unmount();
    renderTab("?tab=runs&layout=tree");
    expect(screen.getByText(`tree of ${JOB}`)).toBeInTheDocument();
  });
});
