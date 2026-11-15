import { describe, it, expect } from "vitest";
import { pollOutcome } from "../jobPoll";

const httpError = (status: number) => Object.assign(new Error(`HTTP ${status}`), { status });

describe("pollOutcome", () => {
  it("reads a 404 poll as unknown: this replica does not have the job", () => {
    expect(pollOutcome(httpError(404))).toBe("unknown");
  });

  it("reads a 500 as an error", () => {
    expect(pollOutcome(httpError(500))).toBe("error");
  });

  it("reads a network error (no status) as an error", () => {
    expect(pollOutcome(new TypeError("Failed to fetch"))).toBe("error");
  });
});
