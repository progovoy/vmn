import { describe, it, expect } from "vitest";
import { diffFiles } from "../diffFiles";

describe("diffFiles", () => {
  it("counts each file's added and removed hunk lines", () => {
    const text = [
      "diff --git a/src/train.py b/src/train.py",
      "index 1..2 100644",
      "--- a/src/train.py",
      "+++ b/src/train.py",
      "@@ -1,3 +1,4 @@",
      " keep",
      "-lr = 0.1",
      "+lr = 0.01",
      "+epochs = 3",
      "diff --git a/old.txt b/new.txt",
      "similarity index 90%",
      "rename from old.txt",
      "rename to new.txt",
      "diff --git a/gone.py b/gone.py",
      "deleted file mode 100644",
      "--- a/gone.py",
      "+++ /dev/null",
      "@@ -1 +0,0 @@",
      "---x",
    ].join("\n");
    expect(diffFiles(text)).toEqual([
      { path: "src/train.py", added: 2, removed: 1 },
      { path: "new.txt", added: 0, removed: 0 },
      { path: "gone.py", added: 0, removed: 1 },
    ]);
  });

  it("drops the run-vs-run diff's materialised <verstr>/ directory", () => {
    const text = [
      "diff --git a/v-prev/optim.py b/v-run/optim.py",
      "--- a/v-prev/optim.py",
      "+++ b/v-run/optim.py",
      "@@ -1 +1 @@",
      "-a",
      "+b",
    ].join("\n");
    expect(diffFiles(text, "v-run")).toEqual([{ path: "optim.py", added: 1, removed: 1 }]);
  });

  it("is empty without a diff", () => {
    expect(diffFiles("")).toEqual([]);
  });
});
