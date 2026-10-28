/** Plan 28 A0: an app's store settings over GET/PUT `.../apps/{app}/settings`. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiSettings } from "../apiSettings";

const BODY = { text: "ui: {group_aggregate: best}\n", settings: { ui: { group_aggregate: "best" } }, error: null };

describe("apiSettings", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(BODY), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("reads an app's settings by its tag", async () => {
    expect(await apiSettings.get("w", "root/svc")).toEqual(BODY);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/workspaces/w/apps/root-svc/settings");
    expect(init.method).toBe("GET");
  });

  it("writes the text as JSON with PUT", async () => {
    await apiSettings.save("w", "app", BODY.text);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/workspaces/w/apps/app/settings");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ text: BODY.text });
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("throws the server's 400 detail with its status", async () => {
    fetchMock.mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: "invalid ui.group_aggregate: 'sum'" }), { status: 400 }));
    await expect(apiSettings.save("w", "app", "x")).rejects.toMatchObject({
      message: "invalid ui.group_aggregate: 'sum'", status: 400,
    });
  });
});
