/** What every board row and card shares: a click anywhere but a control
 *  opens the run, the selection checkbox, and the `+N more` button. */
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import RowCheckbox from "../RowCheckbox";
import MoreButton from "../MoreButton";
import { useRowNavigate } from "../../hooks/useRowNavigate";

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function Row() {
  const onClick = useRowNavigate("/run/x");
  return (
    <div data-testid="row" onClick={onClick}>
      <span>cell</span><a href="#l">link</a><input aria-label="box" /><button>btn</button>
    </div>
  );
}

const renderRow = () => render(
  <MemoryRouter initialEntries={["/"]}>
    <Routes><Route path="*" element={<><Row /><Where /></>} /></Routes>
  </MemoryRouter>,
);

describe("useRowNavigate", () => {
  it("opens the run on a click outside the row's controls", () => {
    renderRow();
    fireEvent.click(screen.getByText("link"));
    fireEvent.click(screen.getByLabelText("box"));
    fireEvent.click(screen.getByText("btn"));
    expect(screen.getByTestId("where").textContent).toBe("/");
    fireEvent.click(screen.getByText("cell"));
    expect(screen.getByTestId("where").textContent).toBe("/run/x");
  });
});

describe("RowCheckbox", () => {
  it("toggles its run, shift-click extending the range", () => {
    const onToggle = vi.fn();
    render(<RowCheckbox verstr="0.1" checked={false} onToggle={onToggle} />);
    const box = screen.getByRole("checkbox", { name: "Select 0.1" });
    expect(box).not.toBeChecked();
    fireEvent.click(box, { shiftKey: true });
    expect(onToggle).toHaveBeenCalledWith("0.1", true);
  });
});

describe("MoreButton", () => {
  it("reads +N more and loads the group's key", () => {
    const onMore = vi.fn();
    render(<MoreButton item={{ item: "more", key: "g", remaining: 7, state: "idle" } as never} onMore={onMore} />);
    fireEvent.click(screen.getByRole("button", { name: "+7 more" }));
    expect(onMore).toHaveBeenCalledWith("g");
  });

  it("is disabled while loading and an alert on error", () => {
    const { rerender } = render(<MoreButton item={{ item: "more", key: "g", remaining: 7, state: "loading" } as never} onMore={() => {}} />);
    expect(screen.getByRole("button")).toBeDisabled();
    rerender(<MoreButton item={{ item: "more", key: "g", remaining: 7, state: "error" } as never} onMore={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load them, retry");
  });
});
