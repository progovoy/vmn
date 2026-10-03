// Source-level edits of ```vmn-panel blocks in a report's markdown.
import { stringify } from "yaml";

export interface PanelBlock {
  /** Offsets of the whole fenced block (fences included). */
  start: number;
  end: number;
  raw: string;
}

const FENCE = /^```vmn-panel[ \t]*\n([\s\S]*?)^```[ \t]*$/gm;

export function findPanelBlocks(source: string): PanelBlock[] {
  return [...source.matchAll(FENCE)].map((m) => ({ start: m.index!, end: m.index! + m[0].length, raw: m[1] }));
}

export function specToBlock(spec: Record<string, unknown>): string {
  return "```vmn-panel\n" + stringify(spec) + "```\n";
}

export function insertPanelBlock(source: string, at: number, spec: Record<string, unknown>): string {
  const before = source.slice(0, at).replace(/\n*$/, "");
  const after = source.slice(at).replace(/^\n*/, "");
  return `${before ? before + "\n\n" : ""}${specToBlock(spec)}${after ? "\n" + after : ""}`;
}

/** Replace the first block whose YAML equals `raw` (the text the preview rendered). */
export function replacePanelBlock(source: string, raw: string, spec: Record<string, unknown>): string {
  const block = findPanelBlocks(source).find((b) => b.raw === raw);
  if (!block) return source;
  const tail = source.slice(block.end).replace(/^\n/, "");
  return source.slice(0, block.start) + specToBlock(spec) + tail;
}

/** Cheap structural check; the server's parser is authoritative. */
export function queryProblem(query: string): string | null {
  if (!query.trim()) return "query is empty";
  let depth = 0;
  let quote: string | null = null;
  for (const ch of query) {
    if (quote) { if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "(") depth += 1;
    else if (ch === ")" && --depth < 0) return "unbalanced parentheses";
  }
  if (quote) return "unterminated quote";
  return depth ? "unbalanced parentheses" : null;
}
