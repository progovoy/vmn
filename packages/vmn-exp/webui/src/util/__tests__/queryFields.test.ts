/** Plan 20 D10 follow-up: text with a query operator but no field the query
 *  language knows (`lr=0.1`) is a search, not a query the server refuses. */
import { describe, it, expect } from "vitest";
import { fieldHint, unknownFields } from "../queryFields";

describe("unknownFields", () => {
  it("names a compared word that is no field", () => {
    expect(unknownFields("lr=0.1")).toEqual(["lr"]);
    expect(unknownFields("lr = 0.1 and metrics.loss < 1")).toEqual(["lr"]);
    expect(unknownFields("model not in ('a')")).toEqual(["model"]);
  });

  it("knows the row fields, the dotted prefixes and the search pseudo-field", () => {
    expect(unknownFields('name ~ "x" and status = "failed" and archived = true')).toEqual([]);
    expect(unknownFields("metrics.loss < 1 or params.lr >= 0.1 or tags.team = 'a'")).toEqual([]);
    expect(unknownFields('outputs."model.pkl".digest = "abc" and env.packages.torch ~ "2"')).toEqual([]);
    expect(unknownFields('text ~ "batch"')).toEqual([]);
    expect(unknownFields('metrics.loss < 1 and not status = "failed" or (x.y = 1)')).toEqual(["x.y"]);
  });

  it("knows ancestor fields, with and without a selector (plan 28 N1)", () => {
    expect(unknownFields('up.params.trade_date = "d1" and up.tags.kind = "study"')).toEqual([]);
    expect(unknownFields('up(tags.kind = "study").params.group = "fx"')).toEqual([]);
    expect(unknownFields('up.params."odd/key" = 1')).toEqual([]);
  });

  it("ignores operators inside quoted values", () => {
    expect(unknownFields('note ~ "lr=0.1"')).toEqual([]);
  });
});

describe("fieldHint", () => {
  const facets = { metric_keys: ["loss"], param_keys: ["lr"] };

  it("suggests the param or metric the bare name stands for", () => {
    expect(fieldHint("lr=0.1", facets)).toEqual({ field: "lr", suggestion: "params.lr=0.1" });
    expect(fieldHint("loss < 0.5", facets)).toEqual({ field: "loss", suggestion: "metrics.loss < 0.5" });
  });

  it("names the field without a suggestion when the app has no such key", () => {
    expect(fieldHint("foo = 1", facets)).toEqual({ field: "foo", suggestion: null });
  });

  it("is null for a valid query or plain text", () => {
    expect(fieldHint("params.lr = 0.1", facets)).toBeNull();
    expect(fieldHint("batch size", facets)).toBeNull();
  });
});
