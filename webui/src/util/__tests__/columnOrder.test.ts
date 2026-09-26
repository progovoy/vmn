import { describe, it, expect } from "vitest";
import { orderedKeys, moveKey, togglePin } from "../columnOrder";

describe("orderedKeys", () => {
  it("no col param keeps default order", () => {
    expect(orderedKeys(["a", "b", "c"], [], [])).toEqual(["a", "b", "c"]);
  });

  it("listed keys appear first, then remaining defaults in default order", () => {
    expect(orderedKeys(["a", "b", "c"], ["b", "a"], [])).toEqual(["b", "a", "c"]);
  });

  it("unknown keys in order are ignored", () => {
    expect(orderedKeys(["a", "b"], ["x", "b", "y"], [])).toEqual(["b", "a"]);
  });

  it("pinned keys come first before unpinned, respecting order within group", () => {
    expect(orderedKeys(["a", "b", "c"], ["c", "b"], ["b"])).toEqual(["b", "c", "a"]);
  });

  it("hidden pinned key (not in defaultKeys) is not rendered", () => {
    expect(orderedKeys(["a", "b"], ["a", "b"], ["z"])).toEqual(["a", "b"]);
  });

  it("pinned key not in order still appears first in defaultKeys order", () => {
    expect(orderedKeys(["a", "b", "c"], [], ["b"])).toEqual(["b", "a", "c"]);
  });

  it("all keys pinned and ordered", () => {
    expect(orderedKeys(["a", "b", "c"], ["c", "b", "a"], ["c", "b", "a"])).toEqual(["c", "b", "a"]);
  });
});

describe("moveKey", () => {
  it("moves a key forward within unpinned group", () => {
    expect(moveKey([], "a", 1, ["a", "b", "c"], [])).toEqual(["b", "a", "c"]);
  });

  it("clamps at the start of the unpinned group", () => {
    expect(moveKey([], "a", -1, ["a", "b", "c"], [])).toEqual(["a", "b", "c"]);
  });

  it("clamps at the end of the unpinned group", () => {
    expect(moveKey([], "c", 1, ["a", "b", "c"], [])).toEqual(["a", "b", "c"]);
  });

  it("does not move a pinned key past the end of the pinned group into unpinned", () => {
    // rendered: ["a","b","c"] where a,b are pinned; b is last pinned — stays
    expect(moveKey([], "b", 1, ["a", "b", "c"], ["a", "b"])).toEqual(["a", "b", "c"]);
  });

  it("does not move an unpinned key past the start of its group into pinned", () => {
    // rendered: ["a","b","c"] where a is pinned; b is first unpinned — stays
    expect(moveKey([], "b", -1, ["a", "b", "c"], ["a"])).toEqual(["a", "b", "c"]);
  });

  it("clamps at the start of the pinned group", () => {
    // rendered: ["a","b","c"] where a,b are pinned; a is first — stays
    expect(moveKey([], "a", -1, ["a", "b", "c"], ["a", "b"])).toEqual(["a", "b", "c"]);
  });

  it("moves a key backward within unpinned group", () => {
    expect(moveKey([], "c", -1, ["a", "b", "c"], [])).toEqual(["a", "c", "b"]);
  });

  it("moves a pinned key forward within the pinned group", () => {
    // rendered: ["a","b","c"] where a,b pinned; move a +1 → ["b","a","c"]
    expect(moveKey([], "a", 1, ["a", "b", "c"], ["a", "b"])).toEqual(["b", "a", "c"]);
  });
});

describe("togglePin", () => {
  it("adds a key not yet in pinned", () => {
    expect(togglePin(["a"], "b")).toEqual(["a", "b"]);
  });

  it("removes a key already in pinned", () => {
    expect(togglePin(["a", "b"], "a")).toEqual(["b"]);
  });

  it("starts from empty and adds a key", () => {
    expect(togglePin([], "a")).toEqual(["a"]);
  });

  it("removing the only key yields an empty array", () => {
    expect(togglePin(["x"], "x")).toEqual([]);
  });
});
