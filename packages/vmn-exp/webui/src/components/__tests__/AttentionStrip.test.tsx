/** Plan 20 C6: the attention strip above the board — stuck · failed in 24h ·
 *  running from experiments-status, each part a filter link. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { AppStatus } from "../../shell/contracts";
import AttentionStrip from "../AttentionStrip";

const NOW = Date.parse("2026-10-13T12:00:00Z");
const status = (o: Partial<AppStatus["counts"]>, failed_recent = 0): AppStatus => ({
  total: 99,
  counts: { created: 0, running: 0, stuck: 0, succeeded: 0, failed: 0, ...o },
  failed_recent,
  rollup: null,
});

function strip(s: AppStatus | undefined, path = "/ws/w/app/a", onFollow = vi.fn()) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AttentionStrip status={s} now={NOW} onFollow={onFollow} />
    </MemoryRouter>,
  );
  return onFollow;
}
const search = (name: RegExp) =>
  new URLSearchParams(screen.getByRole("link", { name }).getAttribute("href")!.split("?")[1]);

afterEach(() => vi.useRealTimers());

describe("AttentionStrip", () => {
  it("reads stuck · failed in 24h · running as a status region", () => {
    strip(status({ stuck: 40, running: 12, failed: 7 }, 3));
    const region = screen.getByRole("status");
    expect(region).toHaveTextContent("40 stuck · 3 failed in 24h · 12 running");
    expect(screen.getByRole("link", { name: "40 stuck" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "3 failed in 24h" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "12 running" })).toBeInTheDocument();
  });

  it("is hidden when nothing is stuck and nothing failed in the last 24h", () => {
    strip(status({ running: 5, failed: 4 }, 0));
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("is hidden while the status is unknown", () => {
    strip(undefined);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("leaves out a zero part", () => {
    strip(status({ stuck: 2 }, 0));
    expect(screen.getByRole("status")).toHaveTextContent(/^\s*⚠?\s*2 stuck\s*$/);
    expect(screen.queryByRole("link", { name: /failed/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /running/ })).toBeNull();
  });

  it("links stuck and running to their status token, replacing the other filters", () => {
    strip(status({ stuck: 1, running: 2 }), "/ws/w/app/a?q=metrics.loss%20%3C%201&status=failed&branch=dev&search=x&archived=1&sort=loss&hide=c%3Anote");
    const stuck = search(/stuck/);
    expect(stuck.get("status")).toBe("stuck");
    for (const k of ["q", "branch", "search", "archived"]) expect(stuck.has(k)).toBe(false);
    // The view's shape (sort, columns) stays.
    expect(stuck.get("sort")).toBe("loss");
    expect(stuck.get("hide")).toBe("c:note");
    expect(search(/running/).get("status")).toBe("running");
  });

  it("links recent failures to failed runs finished in the last 24h, newest first", () => {
    strip(status({ failed: 9 }, 3));
    const failed = search(/failed in 24h/);
    expect(failed.get("status")).toBe("failed");
    expect(failed.get("q")).toBe('finished_at >= "2026-10-12T12:00:00Z"');
    expect(failed.get("sort")).toBe("finished_at");
    expect(failed.get("order")).toBe("desc");
  });

  it("tells the board when a link is followed", () => {
    const onFollow = strip(status({ stuck: 1 }));
    fireEvent.click(screen.getByRole("link", { name: "1 stuck" }));
    expect(onFollow).toHaveBeenCalled();
  });
});
