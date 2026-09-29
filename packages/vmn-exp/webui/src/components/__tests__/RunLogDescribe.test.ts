import { describe, expect, it } from "vitest";
import { describeEntry } from "../RunLog";
import type { LogEntry } from "../../types";

describe("describeEntry", () => {
  it("renders an alert with its level, title and text", () => {
    const e = { type: "alert", timestamp: "2026-01-01T00:00:00Z", level: "error", title: "loss diverged", text: "nan at step 9" } as LogEntry;
    expect(describeEntry(e)).toBe("alert [error]: loss diverged: nan at step 9");
  });

  it("renders an alert without text", () => {
    const e = { type: "alert", timestamp: "2026-01-01T00:00:00Z", level: "info", title: "epoch done" } as LogEntry;
    expect(describeEntry(e)).toBe("alert [info]: epoch done");
  });
});
