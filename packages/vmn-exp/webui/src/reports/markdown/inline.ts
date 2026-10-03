import { inlineText, type Inline } from "./ast";

const PUNCT = /[!-/:-@[-`{-~]/;
const DELIMS: Record<string, { n: number; type: "emphasis" | "strong" | "delete" }[]> = {
  "*": [{ n: 2, type: "strong" }, { n: 1, type: "emphasis" }],
  _: [{ n: 2, type: "strong" }, { n: 1, type: "emphasis" }],
  "~": [{ n: 2, type: "delete" }, { n: 1, type: "delete" }],
};

const isSpace = (c: string | undefined) => c === undefined || /\s/.test(c);
const isWord = (c: string | undefined) => c !== undefined && /[\p{L}\p{N}]/u.test(c);

function runLength(s: string, i: number): number {
  let j = i;
  while (s[j] === s[i]) j += 1;
  return j - i;
}

/** End index (exclusive) of the code span opening at i, or -1. */
function codeSpanEnd(s: string, i: number): number {
  const n = runLength(s, i);
  for (let j = s.indexOf("`", i + n); j !== -1; j = s.indexOf("`", j)) {
    const m = runLength(s, j);
    if (m === n) return j + m;
    j += m;
  }
  return -1;
}

/** Index after the `]` closing the bracket at i (nesting, escapes, code). */
function bracketEnd(s: string, i: number): number {
  let depth = 0;
  for (let j = i; j < s.length; j += 1) {
    const c = s[j];
    if (c === "\\") j += 1;
    else if (c === "`") {
      const e = codeSpanEnd(s, j);
      if (e !== -1) j = e - 1;
      else j += runLength(s, j) - 1;
    } else if (c === "[") depth += 1;
    else if (c === "]" && --depth === 0) return j + 1;
  }
  return -1;
}

/** Parses `(dest "title")` at i; returns the href and the index after `)`. */
function linkDest(s: string, i: number): { href: string; end: number } | null {
  if (s[i] !== "(") return null;
  const m = s.slice(i).match(/^\(\s*(?:<([^<>\n]*)>|((?:[^\s()\\]|\\.|\((?:[^\s()\\]|\\.)*\))*))(?:\s+("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\((?:[^()\\]|\\.)*\)))?\s*\)/);
  if (!m) return null;
  const href = (m[1] ?? m[2] ?? "").replace(/\\([!-/:-@[-`{-~])/g, "$1");
  return { href, end: i + m[0].length };
}

/** Index of the closer for a delimiter run of `n` chars `c` searched from i. */
function findCloser(s: string, i: number, c: string, n: number): number {
  for (let j = i; j < s.length; j += 1) {
    const ch = s[j];
    if (ch === "\\") j += 1;
    else if (ch === "`") {
      const e = codeSpanEnd(s, j);
      j = (e !== -1 ? e : j + runLength(s, j)) - 1;
    } else if (ch === "[") {
      const e = bracketEnd(s, j);
      const d = e === -1 ? null : linkDest(s, e);
      if (d) j = d.end - 1;
    } else if (ch === c) {
      const len = runLength(s, j);
      const rightFlanking = !isSpace(s[j - 1]);
      const intraword = c === "_" && isWord(s[j + len]);
      if (len >= n && rightFlanking && !intraword && j > i) return len === n ? j : j + len - n;
      j += len - 1;
    }
  }
  return -1;
}

function pushText(out: Inline[], value: string) {
  const last = out[out.length - 1];
  if (last?.type === "text") last.value += value;
  else out.push({ type: "text", value });
}

function tryDelimiter(s: string, i: number, out: Inline[]): number {
  const c = s[i];
  const len = runLength(s, i);
  if (isSpace(s[i + len]) || (c === "_" && isWord(s[i - 1]))) return -1;
  for (const { n, type } of DELIMS[c]) {
    if (len < n) continue;
    const close = findCloser(s, i + n, c, n);
    if (close === -1) continue;
    out.push({ type, children: parseInline(s.slice(i + n, close)) });
    return close + n;
  }
  return -1;
}

function tryLink(s: string, i: number, out: Inline[]): number {
  const image = s[i] === "!";
  const open = image ? i + 1 : i;
  const close = bracketEnd(s, open);
  const dest = close === -1 ? null : linkDest(s, close);
  if (!dest) return -1;
  const label = parseInline(s.slice(open + 1, close - 1));
  if (image) {
    out.push({ type: "image", src: dest.href, alt: inlineText(label) });
  } else out.push({ type: "link", href: dest.href, children: label });
  return dest.end;
}

function tryAutolink(s: string, i: number, out: Inline[]): number {
  const m = s.slice(i).match(/^<((?:https?:\/\/|mailto:)[^\s<>]+)>/i);
  if (!m) return -1;
  out.push({ type: "link", href: m[1], children: [{ type: "text", value: m[1] }] });
  return i + m[0].length;
}

function tryCode(s: string, i: number, out: Inline[]): number {
  const end = codeSpanEnd(s, i);
  const n = runLength(s, i);
  if (end === -1) {
    pushText(out, s.slice(i, i + n));
    return i + n;
  }
  let value = s.slice(i + n, end - n).replace(/\n/g, " ");
  if (/^ .*[^ ].* $/.test(value)) value = value.slice(1, -1);
  out.push({ type: "code", value });
  return end;
}

function hardBreak(out: Inline[]) {
  const last = out[out.length - 1];
  if (last?.type === "text") last.value = last.value.replace(/ +$/, "");
  out.push({ type: "break" });
}

/** Parses inline markdown (one paragraph's text, lines joined by "\n"). */
export function parseInline(s: string): Inline[] {
  const out: Inline[] = [];
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    let next = -1;
    if (c === "\\" && s[i + 1] === "\n") {
      hardBreak(out);
      next = i + 2;
    } else if (c === "\\" && PUNCT.test(s[i + 1] ?? "")) {
      pushText(out, s[i + 1]);
      next = i + 2;
    } else if (c === "\n" && s[i - 1] === " " && s[i - 2] === " ") {
      hardBreak(out);
      next = i + 1;
    } else if (c === "`") next = tryCode(s, i, out);
    else if (c === "[" || (c === "!" && s[i + 1] === "[")) next = tryLink(s, i, out);
    else if (c === "<") next = tryAutolink(s, i, out);
    else if (c in DELIMS) next = tryDelimiter(s, i, out);
    if (next === -1) {
      const len = c in DELIMS ? runLength(s, i) : 1;
      pushText(out, s.slice(i, i + len));
      next = i + len;
    }
    i = next;
  }
  return out;
}
