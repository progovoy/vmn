import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { useMenuKeys } from "../useMenuKeys";

function Menu({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const close = () => { setOpen(false); onClose(); };
  const onKeyDown = useMenuKeys(open, menu, close);
  return (
    <>
      <button onClick={() => setOpen(true)}>open</button>
      {open && (
        <div role="menu" ref={menu} onKeyDown={onKeyDown}>
          {["a", "b", "c"].map((n) => <button key={n} role="menuitem">{n}</button>)}
        </div>
      )}
    </>
  );
}

const item = (name: string) => screen.getByRole("menuitem", { name });
const key = (k: string) => fireEvent.keyDown(document.activeElement!, { key: k });

describe("useMenuKeys", () => {
  it("focuses the first item when the menu opens", () => {
    render(<Menu />);
    fireEvent.click(screen.getByText("open"));
    expect(item("a")).toHaveFocus();
  });

  it("arrows move and wrap", () => {
    render(<Menu />);
    fireEvent.click(screen.getByText("open"));
    key("ArrowDown");
    expect(item("b")).toHaveFocus();
    key("ArrowUp");
    key("ArrowUp");
    expect(item("c")).toHaveFocus();
    key("ArrowDown");
    expect(item("a")).toHaveFocus();
  });

  it("Home and End jump to the ends", () => {
    render(<Menu />);
    fireEvent.click(screen.getByText("open"));
    key("End");
    expect(item("c")).toHaveFocus();
    key("Home");
    expect(item("a")).toHaveFocus();
  });

  it("Tab leaves and closes the menu", () => {
    const onClose = vi.fn();
    render(<Menu onClose={onClose} />);
    fireEvent.click(screen.getByText("open"));
    key("Tab");
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("ignores other keys", () => {
    render(<Menu />);
    fireEvent.click(screen.getByText("open"));
    key("x");
    expect(item("a")).toHaveFocus();
  });

  it("treats radio items as items and opens on the checked one", () => {
    function Radios() {
      const menu = useRef<HTMLDivElement>(null);
      const onKeyDown = useMenuKeys(true, menu, () => {});
      return (
        <div role="menu" ref={menu} onKeyDown={onKeyDown}>
          {["x", "y", "z"].map((n) => (
            <button key={n} role="menuitemradio" aria-checked={n === "y"}>{n}</button>
          ))}
        </div>
      );
    }
    render(<Radios />);
    const radio = (name: string) => screen.getByRole("menuitemradio", { name });
    expect(radio("y")).toHaveFocus();
    key("ArrowDown");
    expect(radio("z")).toHaveFocus();
  });
});
