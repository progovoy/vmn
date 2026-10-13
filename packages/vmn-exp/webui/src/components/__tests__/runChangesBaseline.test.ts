import { describe, it, expect } from "vitest";
import type { BaselineRun, RunBaselines } from "../../apiRunCode";
import {
  baselineChoices, changesSearch, defaultBaseline, resolveBaseline,
} from "../runChangesBaseline";

const run = (verstr: string, idx: number | null = null, name: string | null = null): BaselineRun =>
  ({ verstr, idx, name, status: "succeeded" });

const ALL: RunBaselines = {
  best: run("v-best", 7, "best"),
  previous: run("v-prev", 3),
  rerun_of: run("v-orig", 2),
  forked_from: run("v-fork", 1),
  parent: run("v-parent", 0, "sweep"),
  base: run("v-self", 9, "me"),
};

describe("defaultBaseline (D7)", () => {
  it("is base when the run captured a patch", () => {
    expect(defaultBaseline(ALL)).toBe("base");
  });

  it("is previous for a clean-tree run", () => {
    expect(defaultBaseline({ previous: run("p"), parent: run("o"), best: run("b") })).toBe("previous");
  });

  it("falls back to the first baseline that exists, in D7 order", () => {
    expect(defaultBaseline({ best: run("b"), rerun_of: run("r") })).toBe("rerun_of");
    expect(defaultBaseline({})).toBeNull();
  });
});

describe("baselineChoices", () => {
  it("lists only the existing baselines, in D7 order, labelled @N name", () => {
    const choices = baselineChoices(ALL, null);
    expect(choices.map((c) => c.id)).toEqual(
      ["base", "parent", "forked_from", "rerun_of", "previous", "best"],
    );
    expect(choices.map((c) => c.label)).toEqual([
      "base version", "parent @0 sweep", "forked from @1", "rerun of @2", "previous @3", "best @7 best",
    ]);
    expect(choices[0].verstr).toBeNull();
    expect(choices[4].verstr).toBe("v-prev");
  });

  it("adds a requested run that is no baseline as its own choice", () => {
    const choices = baselineChoices({ previous: run("v-prev", 3) }, "v-good");
    expect(choices.map((c) => [c.id, c.verstr])).toEqual([["previous", "v-prev"], ["ref:v-good", "v-good"]]);
    expect(choices[1].label).toBe("vs v-good");
  });

  it("does not repeat a requested run that already is a baseline", () => {
    expect(baselineChoices({ previous: run("v-prev", 3) }, "v-prev")).toHaveLength(1);
  });
});

describe("resolveBaseline", () => {
  const b = { previous: run("v-prev", 3), best: run("v-best", 7) };

  it("takes the requested key, else the baseline whose verstr was requested", () => {
    expect(resolveBaseline(b, "best")).toBe("best");
    expect(resolveBaseline(b, "v-best")).toBe("best");
  });

  it("takes any other requested ref as its own choice", () => {
    expect(resolveBaseline(b, "v-good")).toBe("ref:v-good");
  });

  it("is the D7 default without a request, or for a key that does not exist", () => {
    expect(resolveBaseline(b, null)).toBe("previous");
    expect(resolveBaseline(b, "parent")).toBe("previous");
  });
});

describe("changesSearch", () => {
  it("is the run page query that picks the baseline", () => {
    expect(changesSearch("0.0.1-dev.a+b")).toBe("baseline=0.0.1-dev.a%2Bb");
  });
});
