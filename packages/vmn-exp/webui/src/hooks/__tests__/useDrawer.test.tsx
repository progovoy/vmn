/** The sidebar as an off-canvas drawer below 900px (plan 19 §1.10). */
import { describe, it, expect, afterEach, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { Link, MemoryRouter } from "react-router-dom";
import { useDrawer } from "../useDrawer";

type Listener = (e: { matches: boolean }) => void;
let narrow = true;
const listeners = new Set<Listener>();
const originalMatchMedia = window.matchMedia;

beforeEach(() => {
  narrow = true;
  listeners.clear();
  window.matchMedia = ((query: string) => ({
    get matches() { return query === "(max-width: 899px)" && narrow; },
    media: query,
    addEventListener: (_: string, l: Listener) => listeners.add(l),
    removeEventListener: (_: string, l: Listener) => listeners.delete(l),
  })) as unknown as typeof window.matchMedia;
});
afterEach(() => { window.matchMedia = originalMatchMedia; });

function setNarrow(next: boolean) {
  narrow = next;
  act(() => listeners.forEach((l) => l({ matches: next })));
}

function Harness() {
  const d = useDrawer();
  return (
    <>
      <aside ref={d.sidebarRef} data-testid="sidebar">
        <Link to="/" className="sidebar-brand">brand</Link>
        <nav><Link className="nav-item" to="/elsewhere">First nav</Link></nav>
      </aside>
      <div ref={d.mainRef} data-testid="main-col">
        <button aria-expanded={d.open} onClick={d.toggle}>menu</button>
      </div>
      {d.open && <div data-testid="veil" onClick={d.close} />}
    </>
  );
}

function renderDrawer() {
  render(<MemoryRouter initialEntries={["/start"]}><Harness /></MemoryRouter>);
  return {
    sidebar: screen.getByTestId("sidebar"),
    mainCol: screen.getByTestId("main-col"),
    menu: screen.getByRole("button", { name: "menu" }),
  };
}

const inert = (el: HTMLElement) => el.hasAttribute("inert");

describe("useDrawer", () => {
  it("never makes the desktop sidebar inert", () => {
    narrow = false;
    const { sidebar, mainCol } = renderDrawer();
    expect(inert(sidebar)).toBe(false);
    expect(inert(mainCol)).toBe(false);
  });

  it("keeps the closed drawer inert under the media query", () => {
    const { sidebar, mainCol } = renderDrawer();
    expect(inert(sidebar)).toBe(true);
    expect(inert(mainCol)).toBe(false);
  });

  it("opens onto the first nav link and makes the page inert", () => {
    const { sidebar, mainCol, menu } = renderDrawer();
    menu.focus();
    fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "First nav" })).toHaveFocus();
    expect(inert(sidebar)).toBe(false);
    expect(inert(mainCol)).toBe(true);
  });

  it("closes on Escape and gives focus back to the menu button", () => {
    const { sidebar, mainCol, menu } = renderDrawer();
    menu.focus();
    fireEvent.click(menu);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(menu).toHaveFocus();
    expect(inert(sidebar)).toBe(true);
    expect(inert(mainCol)).toBe(false);
  });

  it("closes on a veil click", () => {
    const { menu } = renderDrawer();
    menu.focus();
    fireEvent.click(menu);
    fireEvent.click(screen.getByTestId("veil"));
    expect(screen.queryByTestId("veil")).toBeNull();
    expect(menu).toHaveFocus();
  });

  it("closes on a navigation", () => {
    const { menu } = renderDrawer();
    fireEvent.click(menu);
    fireEvent.click(screen.getByRole("link", { name: "First nav" }));
    expect(screen.queryByTestId("veil")).toBeNull();
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });

  it("closes when the window widens past the drawer breakpoint", () => {
    const { sidebar, mainCol, menu } = renderDrawer();
    fireEvent.click(menu);
    setNarrow(false);
    expect(screen.queryByTestId("veil")).toBeNull();
    expect(inert(sidebar)).toBe(false);
    expect(inert(mainCol)).toBe(false);
  });

  it("ignores Escape while closed", () => {
    const { sidebar } = renderDrawer();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(inert(sidebar)).toBe(true);
  });
});
