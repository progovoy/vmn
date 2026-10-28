/** Plan 28 P1: the strip's configured parts carry their level as a class,
 *  link to their query, and start from the search the caller gives. */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { AppStatus } from "../../shell/contracts";
import AttentionStrip from "../AttentionStrip";

const NOW = Date.parse("2026-10-13T12:00:00Z");
const STATUS: AppStatus = {
  total: 99, failed_recent: 0, rollup: null,
  counts: { created: 0, running: 0, stuck: 1, succeeded: 0, failed: 0 },
  attention: [
    { key: "unstable", label: "unstable", level: "warn", count: 3, q: 'tags.health = "unstable"' },
    { key: "nonfinite", label: "nonfinite", level: "error", count: 2, q: 'tags.state = "nonfinite"' },
  ],
};

function strip(from?: string, path = "/ws/w/app/a?view=jobs&sort=job:total") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AttentionStrip status={STATUS} now={NOW} from={from} />
    </MemoryRouter>,
  );
}
const href = (name: string) => screen.getByRole("link", { name }).getAttribute("href")!;
const params = (name: string) => new URLSearchParams(href(name).split("?")[1]);

describe("AttentionStrip's configured parts", () => {
  it("read after the built-in ones", () => {
    strip();
    expect(screen.getByRole("status")).toHaveTextContent("1 stuck · 3 unstable · 2 nonfinite");
  });

  it("are coloured by their level", () => {
    strip();
    expect(screen.getByRole("link", { name: "3 unstable" })).toHaveClass("attention-warn");
    expect(screen.getByRole("link", { name: "2 nonfinite" })).toHaveClass("attention-error");
    expect(screen.getByRole("link", { name: "1 stuck" })).toHaveClass("attention-stuck");
  });

  it("link to the board filtered by their query, titled with it", () => {
    strip();
    expect(params("3 unstable").get("q")).toBe('tags.health = "unstable"');
    expect(screen.getByRole("link", { name: "3 unstable" })).toHaveAttribute("title", 'tags.health = "unstable"');
  });

  it("start from the caller's search instead of the page's", () => {
    strip("?view=all&density=compact");
    const p = params("3 unstable");
    expect(p.get("view")).toBe("all");
    expect(p.get("density")).toBe("compact");
    expect(p.has("sort")).toBe(false);
    expect(href("1 stuck").startsWith("/ws/w/app/a?")).toBe(true);
  });
});
