/** Plan 20 B5: a run-page section that opens and closes, remembers that per
 *  user, and keeps its heading for screen readers. */
import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import Disclosure, { DISCLOSURE_KEY } from "../Disclosure";

const toggle = (name: string) => screen.getByRole("button", { name });

beforeEach(() => localStorage.clear());

describe("Disclosure", () => {
  it("is an h2 heading whose button says whether the section is open", () => {
    render(<Disclosure id="log" title="Log"><p>body</p></Disclosure>);
    const heading = screen.getByRole("heading", { level: 2, name: "Log" });
    expect(heading).toContainElement(toggle("Log"));
    expect(toggle("Log")).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("region", { name: "Log" })).toBeInTheDocument();
  });

  it("hides its body while closed and shows it once opened", () => {
    render(<Disclosure id="log" title="Log"><p>body</p></Disclosure>);
    expect(screen.queryByText("body")).not.toBeVisible();
    fireEvent.click(toggle("Log"));
    expect(toggle("Log")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("body")).toBeVisible();
    expect(toggle("Log").getAttribute("aria-controls")).toBe(screen.getByText("body").parentElement!.id);
  });

  it("opens by default when asked to", () => {
    render(<Disclosure id="media" title="Media" defaultOpen><p>body</p></Disclosure>);
    expect(toggle("Media")).toHaveAttribute("aria-expanded", "true");
  });

  it("remembers the user's choice across mounts, over the default", () => {
    const { unmount } = render(<Disclosure id="media" title="Media" defaultOpen><p>body</p></Disclosure>);
    fireEvent.click(toggle("Media"));
    expect(localStorage.getItem(DISCLOSURE_KEY)).toBe(JSON.stringify({ media: false }));
    unmount();
    render(<Disclosure id="media" title="Media" defaultOpen><p>body</p></Disclosure>);
    expect(toggle("Media")).toHaveAttribute("aria-expanded", "false");
  });

  it("follows a default that changes until the user chooses", () => {
    const { rerender } = render(<Disclosure id="comments" title="Comments"><p>body</p></Disclosure>);
    expect(toggle("Comments")).toHaveAttribute("aria-expanded", "false");
    rerender(<Disclosure id="comments" title="Comments" defaultOpen><p>body</p></Disclosure>);
    expect(toggle("Comments")).toHaveAttribute("aria-expanded", "true");
  });

  it("shows a preview while closed, and mounts a lazy body only when open", () => {
    render(
      <Disclosure id="log" title="Log" lazy preview={<p>last entries</p>}>
        <p>full log</p>
      </Disclosure>,
    );
    expect(screen.getByText("last entries")).toBeVisible();
    expect(screen.queryByText("full log")).toBeNull();
    fireEvent.click(toggle("Log"));
    expect(screen.queryByText("last entries")).toBeNull();
    expect(screen.getByText("full log")).toBeVisible();
  });

  it("survives unreadable stored state", () => {
    localStorage.setItem(DISCLOSURE_KEY, "{not json");
    render(<Disclosure id="log" title="Log"><p>body</p></Disclosure>);
    expect(toggle("Log")).toHaveAttribute("aria-expanded", "false");
  });
});
