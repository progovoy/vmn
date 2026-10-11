import { describe, expect, it } from "vitest";
import { describeEntry } from "../RunLog";
import type { LogEntry } from "../../types";

const TS = "2026-01-01T00:00:00Z";

describe("describeEntry of a run's facts", () => {
  it("sums up a features entry with its author", () => {
    const e = {
      type: "features", timestamp: TS, features_version: 1, source: "capture",
      author: { git_user_email: "alice@x.io", writer: "gpu-07" },
      changed: { files: ["loss.py", "train.py"], symbols: ["loss.py::focal_loss"] },
      commits: ["try focal loss"],
    } as LogEntry;
    expect(describeEntry(e)).toBe("features: 2 files, 1 function, 1 commit (alice@x.io)");
  });

  it("names the author as the row does: os user, else writer", () => {
    const e = { type: "features", timestamp: TS, author: { os_user: " ", writer: "gpu-07" } } as LogEntry;
    expect(describeEntry(e)).toBe("features: 0 files, 0 functions, 0 commits (gpu-07)");
  });

  it("leaves the author out when there is none", () => {
    const e = {
      type: "features", timestamp: TS,
      changed: { files: ["a.py"], symbols: ["a.py::f", "a.py::g"] }, commits: ["x", "y"],
    } as LogEntry;
    expect(describeEntry(e)).toBe("features: 1 file, 2 functions, 2 commits");
  });

  it("shows an intent's first line and keywords", () => {
    const e = {
      type: "intent", timestamp: TS, text: "Focal loss for imbalance\n\nMore detail.",
      keywords: ["focal loss", "class imbalance"],
    } as LogEntry;
    expect(describeEntry(e)).toBe("intent: Focal loss for imbalance [focal loss, class imbalance]");
  });

  it("shows an intent without keywords, skipping blank leading lines", () => {
    const e = { type: "intent", timestamp: TS, text: "\n  Label smoothing  \nwhy" } as LogEntry;
    expect(describeEntry(e)).toBe("intent: Label smoothing");
  });
});
