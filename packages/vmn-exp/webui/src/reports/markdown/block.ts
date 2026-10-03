import type { Align, Block } from "./ast";
import { parseInline } from "./inline";

const ATX = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$/;
const FENCE = /^( {0,3})(`{3,}|~{3,})(.*)$/;
const HR = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const QUOTE = /^ {0,3}> ?(.*)$/;
const ITEM = /^( {0,3})([-*+]|(\d{1,9})([.)]))(?:([ \t]+)(.*))?$/;
const SETEXT = /^ {0,3}(=+|-+)[ \t]*$/;
const TABLE_DELIM = /^[ \t]*\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$/;

const isBlank = (line: string | undefined) => line !== undefined && line.trim() === "";
const indentOf = (line: string) => line.length - line.trimStart().length;

interface Item {
  /** Bullet char, or the ordered delimiter prefixed with "1". */
  kind: string;
  start: number;
  indent: number;
  contentIndent: number;
  content: string;
}

function matchItem(line: string): Item | null {
  if (HR.test(line)) return null;
  const m = line.match(ITEM);
  if (!m) return null;
  const indent = m[1].length;
  const marker = m[2].length;
  const gap = m[5]?.length ?? 0;
  const contentIndent = indent + marker + (gap === 0 || gap > 4 ? 1 : gap);
  const ordered = m[3] !== undefined;
  return {
    kind: ordered ? `1${m[4]}` : m[2],
    start: ordered ? Number(m[3]) : 1,
    indent,
    contentIndent,
    content: (gap > 4 ? " ".repeat(gap - 1) : "") + (m[6] ?? ""),
  };
}

function matchFence(line: string): { indent: number; fence: string; lang: string } | null {
  const m = line.match(FENCE);
  if (!m || (m[2][0] === "`" && m[3].includes("`"))) return null;
  return { indent: m[1].length, fence: m[2], lang: m[3].trim().split(/\s+/)[0] ?? "" };
}

/** Lines that end a paragraph (and so a lazy continuation) without a blank line. */
function interruptsParagraph(line: string): boolean {
  if (ATX.test(line) || matchFence(line) || HR.test(line) || QUOTE.test(line)) return true;
  const item = matchItem(line);
  return !!item && item.content.trim() !== "" && item.start === 1;
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  return s.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
}

function cellAlign(cell: string): Align {
  const left = cell.startsWith(":");
  const right = cell.endsWith(":");
  if (left && right) return "center";
  return left ? "left" : right ? "right" : null;
}

function isTableStart(lines: string[], i: number): boolean {
  const head = lines[i];
  const delim = lines[i + 1];
  if (!head.includes("|") || delim === undefined || !delim.includes("-") || !TABLE_DELIM.test(delim)) return false;
  return splitRow(head).length === splitRow(delim).length;
}

function parseTable(lines: string[], i: number): [Block, number] {
  const head = splitRow(lines[i]);
  const align = splitRow(lines[i + 1]).map(cellAlign);
  const rows = [];
  let j = i + 2;
  for (; j < lines.length && !isBlank(lines[j]) && !interruptsParagraph(lines[j]); j += 1) {
    const cells = splitRow(lines[j]);
    rows.push(head.map((_, k) => parseInline(cells[k] ?? "")));
  }
  return [{ type: "table", align, head: head.map((c) => parseInline(c)), rows }, j];
}

function parseFence(lines: string[], i: number): [Block, number] {
  const open = matchFence(lines[i])!;
  const close = new RegExp(`^ {0,3}${open.fence[0] === "`" ? "`" : "~"}{${open.fence.length},}[ \\t]*$`);
  let value = "";
  let j = i + 1;
  for (; j < lines.length && !close.test(lines[j]); j += 1) {
    const line = lines[j];
    value += line.slice(Math.min(open.indent, indentOf(line))) + "\n";
  }
  return [{ type: "code", lang: open.lang, value }, j + 1];
}

function parseQuote(lines: string[], i: number): [Block, number] {
  const inner: string[] = [];
  let j = i;
  for (; j < lines.length; j += 1) {
    const m = lines[j].match(QUOTE);
    if (m) inner.push(m[1]);
    else if (!isBlank(lines[j]) && !isBlank(inner[inner.length - 1]) && !interruptsParagraph(lines[j])) inner.push(lines[j]);
    else break;
  }
  return [{ type: "blockquote", children: parseBlocks(inner.join("\n")) }, j];
}

function trimTrailingBlanks(lines: string[]): string[] {
  let n = lines.length;
  while (n > 0 && isBlank(lines[n - 1])) n -= 1;
  return lines.slice(0, n);
}

function hasInnerBlank(lines: string[]): boolean {
  return lines.some((l, k) => isBlank(l) && k + 1 < lines.length && !isBlank(lines[k + 1]) && indentOf(lines[k + 1]) === 0);
}

function parseList(lines: string[], i: number): [Block, number] {
  const first = matchItem(lines[i])!;
  const items: string[][] = [];
  let cur: string[] = [];
  let contentIndent = 0;
  let tight = true;
  let j = i;
  for (; j < lines.length; j += 1) {
    const line = lines[j];
    const item = matchItem(line);
    const prevBlank = isBlank(lines[j - 1]) && j > i;
    if (isBlank(line)) cur.push("");
    else if (items.length && indentOf(line) >= contentIndent) cur.push(line.slice(contentIndent));
    else if (item && item.kind === first.kind) {
      if (items.length && prevBlank) tight = false;
      cur = [item.content];
      items.push(cur);
      contentIndent = item.contentIndent;
    } else if (!prevBlank && !interruptsParagraph(line)) cur.push(line.trimStart());
    else break;
  }
  const bodies = items.map(trimTrailingBlanks);
  if (bodies.some(hasInnerBlank)) tight = false;
  const blocks = bodies.map((b) => parseBlocks(b.join("\n")));
  return [{ type: "list", ordered: first.kind[0] === "1", start: first.start, tight, items: blocks }, j];
}

function parseParagraph(lines: string[], i: number): [Block, number] {
  const text = [lines[i].trimStart()];
  let j = i + 1;
  for (; j < lines.length; j += 1) {
    const line = lines[j];
    const setext = line.match(SETEXT);
    if (setext) {
      return [{ type: "heading", depth: setext[1][0] === "=" ? 1 : 2, children: parseInline(text.join("\n")) }, j + 1];
    }
    if (isBlank(line) || interruptsParagraph(line)) break;
    text.push(line.trimStart());
  }
  const joined = text.join("\n").replace(/[ \t]+$/, "");
  return [{ type: "paragraph", children: parseInline(joined) }, j];
}

function parseHeading(line: string): Block {
  const m = line.match(ATX)!;
  return { type: "heading", depth: m[1].length, children: parseInline((m[2] ?? "").trim()) };
}

function parseOne(lines: string[], i: number): [Block, number] {
  const line = lines[i];
  if (ATX.test(line)) return [parseHeading(line), i + 1];
  if (matchFence(line)) return parseFence(lines, i);
  if (HR.test(line)) return [{ type: "hr" }, i + 1];
  if (QUOTE.test(line)) return parseQuote(lines, i);
  if (matchItem(line)) return parseList(lines, i);
  if (isTableStart(lines, i)) return parseTable(lines, i);
  return parseParagraph(lines, i);
}

/** Parses markdown source into block nodes (CommonMark/GFM subset). */
export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    if (isBlank(lines[i])) {
      i += 1;
      continue;
    }
    const [block, next] = parseOne(lines, i);
    out.push(block);
    i = next;
  }
  return out;
}
