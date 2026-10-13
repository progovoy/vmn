/** The files a unified diff (`git diff` text) changes, with their added and
 *  removed line counts: the Changes card's list for a run-vs-run diff. */
import type { PatchFile } from "../apiRunCode";

const HEADER = /^diff --git a\/.* b\/(.*)$/;

export function diffFiles(text: string): PatchFile[] {
  const files: PatchFile[] = [];
  let file: PatchFile | null = null;
  let inHunk = false;
  for (const line of text.split("\n")) {
    const header = HEADER.exec(line);
    if (header) {
      file = { path: header[1], added: 0, removed: 0 };
      files.push(file);
      inHunk = false;
    } else if (file && line.startsWith("@@")) {
      inHunk = true;
    } else if (file && inHunk && line.startsWith("+")) {
      file.added += 1;
    } else if (file && inHunk && line.startsWith("-")) {
      file.removed += 1;
    }
  }
  return files;
}
