import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiReports, commentTarget } from "../apiReports";

const ok = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

let fetchMock: ReturnType<typeof vi.fn>;
const call = (i = 0) => fetchMock.mock.calls[i] as [string, RequestInit | undefined];

beforeEach(() => {
  fetchMock = vi.fn(() => ok({}));
  vi.stubGlobal("fetch", fetchMock);
});

describe("apiReports", () => {
  it("lists reports with the archived filter", async () => {
    fetchMock.mockReturnValueOnce(ok({ reports: [] }));
    await apiReports.listReports("w", true);
    expect(call()[0]).toBe("/api/v1/workspaces/w/reports?archived=true");
  });

  it("gets a report, a revision and panel data", async () => {
    await apiReports.getReport("w", "r1");
    await apiReports.getRevision("w", "r1", 3);
    await apiReports.getPanelData("w", "r1", 3, "p a");
    expect(call(0)[0]).toBe("/api/v1/workspaces/w/reports/r1");
    expect(call(1)[0]).toBe("/api/v1/workspaces/w/reports/r1/revisions/3");
    expect(call(2)[0]).toBe("/api/v1/workspaces/w/reports/r1/revisions/3/data/p%20a");
  });

  it("creates, saves, publishes, patches and deletes", async () => {
    await apiReports.createReport("w", { title: "T", body: "b" });
    await apiReports.saveRevision("w", "r1", { base: 1, body: "x", message: "m" });
    await apiReports.publish("w", "r1", { rev: 2, data: {} });
    await apiReports.patchReport("w", "r1", { archived: true });
    await apiReports.deleteReport("w", "r1");
    expect(call(0)[0]).toBe("/api/v1/workspaces/w/reports");
    expect(call(0)[1]?.method).toBe("POST");
    expect(call(1)[0]).toBe("/api/v1/workspaces/w/reports/r1/revisions");
    expect(call(2)[0]).toBe("/api/v1/workspaces/w/reports/r1/publish");
    expect(call(3)[1]?.method).toBe("PATCH");
    expect(JSON.parse(String(call(3)[1]?.body))).toEqual({ archived: true });
    expect(call(4)[1]?.method).toBe("DELETE");
  });

  it("talks to the comments endpoints", async () => {
    const target = commentTarget.run("a/b", "1.0.0-dev.x");
    expect(target).toBe("run:a/b:1.0.0-dev.x");
    expect(commentTarget.report("r1")).toBe("report:r1");
    await apiReports.listComments("w", target);
    await apiReports.addComment("w", { target, text: "hi", reply_to: "c1" });
    await apiReports.editComment("w", target, "c1", { text: "x" });
    await apiReports.deleteComment("w", target, "c1");
    expect(call(0)[0]).toBe(`/api/v1/workspaces/w/comments?target=${encodeURIComponent(target)}`);
    expect(call(1)[0]).toBe("/api/v1/workspaces/w/comments");
    expect(call(2)[0]).toBe(`/api/v1/workspaces/w/comments/${encodeURIComponent(target)}/c1`);
    expect(call(2)[1]?.method).toBe("PATCH");
    expect(call(3)[1]?.method).toBe("DELETE");
  });
});
