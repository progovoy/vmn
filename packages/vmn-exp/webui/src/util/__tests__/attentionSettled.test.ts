/** The attention strip's stuck count leaves out the runs an ended outer run
 *  lost (status_summary.py); its link then lists exactly the counted ones. */
import { describe, it, expect } from "vitest";
import { attentionParts } from "../attention";
import type { AppStatus } from "../../shell/contracts";

const status = (extra: Partial<AppStatus>): AppStatus => ({
  total: 10, failed_recent: 0, rollup: "stuck",
  counts: { created: 0, running: 0, stuck: 2, succeeded: 0, failed: 0 }, ...extra,
});

const stuckSearch = (s: AppStatus) =>
  new URLSearchParams(attentionParts(s, "", Date.now()).find((p) => p.key === "stuck")!.search);

describe("the stuck part with lost runs about", () => {
  it("links to the stuck runs no ended outer run settled", () => {
    const search = stuckSearch(status({ lost: 5, never_started: 1 }));
    expect(search.get("status")).toBe("stuck");
    expect(search.get("q")).toBe("settled = null");
  });

  it("links to every stuck run while none is lost", () => {
    expect(stuckSearch(status({ lost: 0 })).has("q")).toBe(false);
  });
});
