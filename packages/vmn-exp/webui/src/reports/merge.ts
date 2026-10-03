/** Line-based three-way merge (diff3) for report bodies, plan 13 §7.3. */
import { lineDiff } from "./lineDiff";

export type MergeChunk =
  | { kind: "ok"; lines: string[] }
  | { kind: "conflict"; base: string[]; theirs: string[]; yours: string[] };
export type Choice = "base" | "theirs" | "yours" | "both";
export interface MergeResult { chunks: MergeChunk[]; clean: boolean; text?: string }

/** For each base line, the index of its unchanged copy in *other*, else -1. */
function matchBase(base: string, other: string): number[] {
  const out: number[] = [];
  let j = 0;
  for (const d of lineDiff(base, other)) {
    if (d.op === "same") out.push(j++);
    else if (d.op === "del") out.push(-1);
    else j++;
  }
  return out;
}

const same = (x: string[], y: string[]) => x.length === y.length && x.every((l, i) => l === y[i]);

function pickChunk(b: string[], t: string[], y: string[]): MergeChunk | null {
  if (!b.length && !t.length && !y.length) return null;
  if (same(t, b)) return { kind: "ok", lines: y };
  if (same(y, b) || same(t, y)) return { kind: "ok", lines: t };
  return { kind: "conflict", base: b, theirs: t, yours: y };
}

function pushChunk(out: MergeChunk[], c: MergeChunk | null) {
  if (!c) return;
  const last = out[out.length - 1];
  if (c.kind === "ok" && last?.kind === "ok") last.lines.push(...c.lines);
  else if (c.kind === "conflict" || c.lines.length) out.push(c.kind === "ok" ? { kind: "ok", lines: [...c.lines] } : c);
}

export function merge3(base: string, theirs: string, yours: string): MergeResult {
  const [b, t, y] = [base, theirs, yours].map((s) => s.split("\n"));
  const mt = matchBase(base, theirs);
  const my = matchBase(base, yours);
  const chunks: MergeChunk[] = [];
  let [i, jt, jy] = [0, 0, 0];
  for (let k = 0; k <= b.length; k++) {
    const stable = k < b.length && mt[k] >= 0 && my[k] >= 0;
    if (!stable && k < b.length) continue;
    const [et, ey] = stable ? [mt[k], my[k]] : [t.length, y.length];
    pushChunk(chunks, pickChunk(b.slice(i, k), t.slice(jt, et), y.slice(jy, ey)));
    if (stable) pushChunk(chunks, { kind: "ok", lines: [b[k]] });
    [i, jt, jy] = [k + 1, et + 1, ey + 1];
  }
  const clean = chunks.every((c) => c.kind === "ok");
  return { chunks, clean, ...(clean ? { text: resolveText(chunks, []) } : {}) };
}

function chosen(c: Extract<MergeChunk, { kind: "conflict" }>, choice: Choice): string[] {
  return choice === "both" ? [...c.theirs, ...c.yours] : c[choice];
}

/** The merged text with conflict *n* resolved by ``choices[n]`` (default yours). */
export function resolveText(chunks: MergeChunk[], choices: Choice[]): string {
  let n = 0;
  return chunks.flatMap((c) => (c.kind === "ok" ? c.lines : chosen(c, choices[n++] ?? "yours"))).join("\n");
}
