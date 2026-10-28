import { describe, expect, it } from "vitest";
import { expandKeys, isGlob, matchKeys } from "../metricGlob";

const NAMES = ["cv0.grad_norm_mean", "cv1.grad_norm_mean", "cv10.grad_norm_mean", "cv1.loss", "val_a", "val_b"];

describe("metric globs (fnmatch, as define_metric matches)", () => {
  it("tells a glob from a plain name", () => {
    expect(isGlob("cv*.loss")).toBe(true);
    expect(isGlob("val_[ab]")).toBe(true);
    expect(isGlob("val?")).toBe(true);
    expect(isGlob("val_loss")).toBe(false);
  });

  it("matches every key, sorted", () => {
    expect(matchKeys("cv*.grad_norm_mean", NAMES)).toEqual(
      ["cv0.grad_norm_mean", "cv1.grad_norm_mean", "cv10.grad_norm_mean"],
    );
    expect(matchKeys("val_[!a]", NAMES)).toEqual(["val_b"]);
    expect(matchKeys("cv?.loss", NAMES)).toEqual(["cv1.loss"]);
    expect(matchKeys("nothing*", NAMES)).toEqual([]);
  });

  it("keeps a dot literal", () => {
    expect(matchKeys("cv1.*", ["cv1.loss", "cv1xloss"])).toEqual(["cv1.loss"]);
  });

  it("expands globs in a key list, plain names kept, no repeats", () => {
    expect(expandKeys(["cv1.loss", "val_*", "val_a", "missing"], NAMES)).toEqual(
      ["cv1.loss", "val_a", "val_b", "missing"],
    );
  });

  it("keeps a key that names a metric exactly even with glob characters", () => {
    expect(expandKeys(["acc[top1]"], ["acc[top1]", "acct"])).toEqual(["acc[top1]"]);
  });
});
