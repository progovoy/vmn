/** The app-wide run selection hook: every board and the tray read one
 *  store per (workspace, app); a URL `sel` (a shared link) only seeds it. */
import { describe, it, expect, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { useRunSelection } from "../useRunSelection";
import { useLeaderboardView } from "../useLeaderboardView";
import { readPicks, writePicks } from "../../util/runSelection";

beforeEach(() => sessionStorage.clear());

function Picker({ ws, app, id }: { ws: string; app: string; id: string }) {
  const sel = useRunSelection(ws, app);
  return (
    <div>
      <output data-testid={id}>{[...sel.selected].join(",")}</output>
      <button onClick={() => sel.toggleSelected("v1", { verstr: "v1", job: "J" })}>toggle-{id}</button>
      <button onClick={() => sel.setSelected(["v2", "v3"])}>set-{id}</button>
      <button onClick={() => sel.remove("v2")}>remove-{id}</button>
      <button onClick={sel.clear}>clear-{id}</button>
    </div>
  );
}

const shown = (id: string) => screen.getByTestId(id).textContent;

describe("useRunSelection", () => {
  it("shares one selection between components of the same app", () => {
    render(<><Picker ws="w" app="a" id="one" /><Picker ws="w" app="a" id="two" /><Picker ws="w" app="b" id="other" /></>);
    fireEvent.click(screen.getByText("toggle-one"));
    expect(shown("two")).toBe("v1");
    expect(shown("other")).toBe("");
    expect(readPicks("w", "a")).toEqual([{ verstr: "v1", job: "J" }]);
  });

  it("toggles, sets, removes and clears", () => {
    render(<Picker ws="w" app="a" id="p" />);
    fireEvent.click(screen.getByText("set-p"));
    expect(shown("p")).toBe("v2,v3");
    fireEvent.click(screen.getByText("remove-p"));
    expect(shown("p")).toBe("v3");
    fireEvent.click(screen.getByText("toggle-p"));
    expect(shown("p")).toBe("v3,v1");
    fireEvent.click(screen.getByText("toggle-p"));
    expect(shown("p")).toBe("v3");
    fireEvent.click(screen.getByText("clear-p"));
    expect(shown("p")).toBe("");
  });

  it("keeps what it knew of a pick when it is set again", () => {
    writePicks("w", "a", [{ verstr: "v2", job: "J", name: "n" }]);
    render(<Picker ws="w" app="a" id="p" />);
    fireEvent.click(screen.getByText("set-p"));
    expect(readPicks("w", "a")[0]).toEqual({ verstr: "v2", job: "J", name: "n" });
  });

  it("follows a write made outside React", () => {
    render(<Picker ws="w" app="a" id="p" />);
    act(() => writePicks("w", "a", [{ verstr: "x" }]));
    expect(shown("p")).toBe("x");
  });
});

function Board() {
  const view = useLeaderboardView();
  const loc = useLocation();
  return (
    <>
      <output data-testid="board">{[...view.selected].join(",")}</output>
      <output data-testid="search">{loc.search}</output>
    </>
  );
}

const renderAt = (path: string) => render(
  <MemoryRouter initialEntries={[path]}>
    <Routes><Route path="/ws/:ws/app/:app" element={<Board />} /></Routes>
  </MemoryRouter>,
);

describe("the board's selection", () => {
  it("is the app's stored selection", () => {
    writePicks("w", "a", [{ verstr: "kept" }]);
    renderAt("/ws/w/app/a?q=x");
    expect(shown("board")).toBe("kept");
  });

  it("is seeded from a shared link's sel, which then leaves the URL", async () => {
    writePicks("w", "a", [{ verstr: "old" }]);
    renderAt("/ws/w/app/a?q=x&sel=s1&sel=s2");
    expect(shown("board")).toBe("s1,s2");
    expect(readPicks("w", "a").map((p) => p.verstr)).toEqual(["s1", "s2"]);
    expect(await screen.findByText("?q=x")).toBeInTheDocument();
  });
});
