/** The tray's tag edit: `key=value` entries to set and keys to remove. */
import { describe, it, expect } from "vitest";
import { parseTagEdit } from "../tags";

describe("parseTagEdit", () => {
  it("reads several tags to set, separated by commas or new lines", () => {
    expect(parseTagEdit("stage=prod, team = ml\nreviewed", "")).toEqual({
      edit: { set: { stage: "prod", team: "ml", reviewed: "" }, remove: [] },
    });
  });

  it("reads keys to remove, separated by commas or spaces", () => {
    expect(parseTagEdit("", "old, stale tmp")).toEqual({ edit: { set: {}, remove: ["old", "stale", "tmp"] } });
  });

  it("refuses an invalid tag, naming it", () => {
    expect(parseTagEdit("bad key=1", "")).toEqual({
      error: '"bad key=1": use key=value (no spaces in key, no leading -)',
    });
  });

  it("refuses an invalid key to remove", () => {
    expect(parseTagEdit("", "-x")).toEqual({ error: '"-x" is not a tag key' });
  });

  it("refuses an empty edit", () => {
    expect(parseTagEdit(" ", ",")).toEqual({ error: "Add a tag to set or a key to remove" });
  });
});
