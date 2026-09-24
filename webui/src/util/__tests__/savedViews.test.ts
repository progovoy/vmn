import { describe, it, expect, beforeEach } from "vitest";
import { deleteView, listViews, saveView, viewSearch } from "../savedViews";

beforeEach(() => localStorage.clear());

describe("saved views store", () => {
  it("starts empty", () => {
    expect(listViews("w", "app")).toEqual([]);
  });

  it("saves under a per-ws/app key and lists in save order", () => {
    saveView("w", "app", "best", "?sort=loss");
    saveView("w", "app", "failed", "?status=failed");
    expect(listViews("w", "app").map((v) => v.name)).toEqual(["best", "failed"]);
    expect(JSON.parse(localStorage.getItem("vmn_views:w/app")!)).toHaveLength(2);
    expect(listViews("w", "other")).toEqual([]);
  });

  it("drops sel and new params from the stored search", () => {
    saveView("w", "app", "v", "?sort=loss&sel=a&sel=b&new=1&hide=p:x");
    expect(listViews("w", "app")[0].search).toBe("?sort=loss&hide=p%3Ax");
  });

  it("stores an empty search when nothing is left", () => {
    expect(viewSearch("?sel=a")).toBe("");
  });

  it("trims names, overwrites the same name, refuses empty names", () => {
    expect(saveView("w", "app", "  best ", "?a=1")).toBe(true);
    saveView("w", "app", "best", "?a=2");
    expect(listViews("w", "app")).toEqual([{ name: "best", search: "?a=2" }]);
    expect(saveView("w", "app", "   ", "?a=3")).toBe(false);
    expect(listViews("w", "app")).toHaveLength(1);
  });

  it("deletes by name", () => {
    saveView("w", "app", "a", "?x=1");
    saveView("w", "app", "b", "?x=2");
    deleteView("w", "app", "a");
    expect(listViews("w", "app").map((v) => v.name)).toEqual(["b"]);
  });

  it("reads corrupt or wrongly shaped storage as empty", () => {
    localStorage.setItem("vmn_views:w/app", "{not json");
    expect(listViews("w", "app")).toEqual([]);
    localStorage.setItem("vmn_views:w/app", JSON.stringify({ name: "x" }));
    expect(listViews("w", "app")).toEqual([]);
    localStorage.setItem("vmn_views:w/app", JSON.stringify([{ name: "ok", search: "?a=1" }, { bad: 1 }]));
    expect(listViews("w", "app")).toEqual([{ name: "ok", search: "?a=1" }]);
  });
});
