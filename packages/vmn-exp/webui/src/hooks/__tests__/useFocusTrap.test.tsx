import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { useFocusTrap } from "../useFocusTrap";

function Dialog({ withInitial }: { withInitial?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const initial = useRef<HTMLInputElement>(null);
  useFocusTrap(ref, withInitial ? { initialFocus: initial } : undefined);
  return (
    <div ref={ref}>
      <button>first</button>
      <input ref={initial} aria-label="middle" />
      <button disabled>off</button>
      <button>last</button>
      <button tabIndex={-1}>row</button>
    </div>
  );
}

function Harness({ withInitial }: { withInitial?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>opener</button>
      <button onClick={() => setOpen(false)}>closer</button>
      {open && <Dialog withInitial={withInitial} />}
    </>
  );
}

function openTrap(withInitial?: boolean) {
  render(<Harness withInitial={withInitial} />);
  const opener = screen.getByText("opener");
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

describe("useFocusTrap", () => {
  it("focuses the first focusable element when it activates", () => {
    openTrap();
    expect(screen.getByText("first")).toHaveFocus();
  });

  it("focuses initialFocus when given", () => {
    openTrap(true);
    expect(screen.getByLabelText("middle")).toHaveFocus();
  });

  it("Tab on the last element cycles to the first", () => {
    openTrap();
    screen.getByText("last").focus();
    fireEvent.keyDown(document.activeElement!, { key: "Tab" });
    expect(screen.getByText("first")).toHaveFocus();
  });

  it("Shift+Tab on the first element cycles to the last enabled one", () => {
    openTrap();
    fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
    expect(screen.getByText("last")).toHaveFocus();
  });

  it("never cycles onto an element taken out of the tab order", () => {
    openTrap();
    screen.getByText("last").focus();
    fireEvent.keyDown(document.activeElement!, { key: "Tab" });
    expect(screen.getByText("first")).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
    expect(screen.getByText("last")).toHaveFocus();
  });

  it("leaves Tab between inner elements to the browser", () => {
    openTrap();
    const ev = fireEvent.keyDown(document.activeElement!, { key: "Tab" });
    expect(ev).toBe(true); // not prevented
    expect(screen.getByText("first")).toHaveFocus();
  });

  it("restores focus to the previously focused element when it deactivates", () => {
    const opener = openTrap();
    expect(opener).not.toHaveFocus();
    fireEvent.click(screen.getByText("closer"));
    expect(opener).toHaveFocus();
  });
});
