/** The log's writer badge (plan 20 E6): a class at a readable size, never an inline 10px. */
import { describe, it, expect, vi, beforeAll } from "vitest";
import { render } from "@testing-library/react";

vi.mock("../../apiRun", () => ({ runLog: vi.fn() }));

import RunLog from "../RunLog";
import type { LogEntry } from "../../types";

type Fs = { readFileSync(path: string, encoding: "utf8"): string };
let css = "";
beforeAll(async () => {
  const fs: Fs = await import(/* @vite-ignore */ "node:fs" as string);
  css = fs.readFileSync("src/components/RunLog.css", "utf8");
});

const entry = { type: "note", text: "hi", timestamp: "2026-01-01T00:00:00Z", _writer: "gpu-07" } as LogEntry;

describe("RunLog writer badge", () => {
  it("is styled by its class, with no inline font size", () => {
    const c = render(<RunLog ws="w" app="a" verstr="v" tail={[entry]} total={1} />).container;
    const badge = c.querySelector(".log-writer")!;
    expect(badge).toHaveTextContent("gpu-07");
    expect(badge.getAttribute("style") ?? "").not.toMatch(/font-size/);
  });

  it("sets the badge at 11px or more and keeps it on one line", () => {
    const rule = css.match(/\.log-writer\s*\{([^}]*)\}/);
    expect(rule).not.toBeNull();
    expect(Number(rule![1].match(/font-size:\s*([\d.]+)px/)![1])).toBeGreaterThanOrEqual(11);
    expect(rule![1]).toMatch(/white-space:\s*nowrap/);
  });
});
