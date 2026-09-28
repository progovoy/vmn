import { describe, it, expect } from "vitest";
import {
  artifactKind, parseDelimited, truncateText, TEXT_PREVIEW_BYTES,
} from "../artifactKinds";
import { buildArtifactTree } from "../artifactTree";

describe("artifactKind", () => {
  it.each([
    ["plot.png", "image"], ["a/b/Photo.JPG", "image"], ["x.jpeg", "image"],
    ["anim.gif", "image"], ["logo.svg", "image"], ["p.webp", "image"],
    ["data.csv", "table"], ["data.tsv", "table"],
    ["conf.json", "text"], ["conf.yaml", "text"], ["conf.yml", "text"],
    ["notes.txt", "text"], ["train.log", "text"], ["README.md", "text"],
    ["model.pt", "binary"], ["checkpoint.bin", "binary"], ["noext", "binary"],
  ])("%s -> %s", (name, kind) => {
    expect(artifactKind(name)).toBe(kind);
  });
});

describe("parseDelimited", () => {
  it("splits rows and cells", () => {
    expect(parseDelimited("a,b\n1,2\n", ",")).toEqual([["a", "b"], ["1", "2"]]);
  });

  it("honours quotes, escaped quotes and delimiters inside quotes", () => {
    expect(parseDelimited('name,desc\n"x, y","say ""hi"""\n', ",")).toEqual([
      ["name", "desc"], ["x, y", 'say "hi"'],
    ]);
  });

  it("keeps newlines inside quoted cells and handles CRLF", () => {
    expect(parseDelimited('a,b\r\n"l1\nl2",3\r\n', ",")).toEqual([["a", "b"], ["l1\nl2", "3"]]);
  });

  it("parses tabs for tsv", () => {
    expect(parseDelimited("a\tb\n1\t2", "\t")).toEqual([["a", "b"], ["1", "2"]]);
  });

  it("stops after maxRows rows", () => {
    const text = Array.from({ length: 300 }, (_, i) => `${i},x`).join("\n");
    const rows = parseDelimited(text, ",", 101);
    expect(rows).toHaveLength(101);
    expect(rows[100]).toEqual(["100", "x"]);
  });
});

describe("truncateText", () => {
  it("leaves short text alone", () => {
    expect(truncateText("hello")).toEqual({ text: "hello", truncated: false });
  });

  it("cuts text past the preview limit", () => {
    const big = "a".repeat(TEXT_PREVIEW_BYTES + 10);
    const out = truncateText(big);
    expect(out.truncated).toBe(true);
    expect(out.text.length).toBe(TEXT_PREVIEW_BYTES);
  });
});

describe("buildArtifactTree", () => {
  it("nests by path component, folders first then files, sorted", () => {
    const tree = buildArtifactTree([
      { name: "z.txt", size: 1 },
      { name: "plots/b.png", size: 2 },
      { name: "plots/a.png", size: 3 },
      { name: "plots/deep/c.csv", size: 4 },
    ]);
    expect(tree.map((n) => n.label)).toEqual(["plots", "z.txt"]);
    const plots = tree[0];
    expect(plots.kind).toBe("dir");
    if (plots.kind !== "dir") throw new Error("dir");
    expect(plots.path).toBe("plots");
    expect(plots.children.map((n) => n.label)).toEqual(["deep", "a.png", "b.png"]);
    const leaf = plots.children[1];
    expect(leaf.kind === "file" && leaf.artifact).toEqual({ name: "plots/a.png", size: 3 });
  });

  it("keeps a flat list flat", () => {
    const tree = buildArtifactTree([{ name: "b", size: 1 }, { name: "a", size: 1 }]);
    expect(tree.map((n) => [n.kind, n.label])).toEqual([["file", "a"], ["file", "b"]]);
  });
});
