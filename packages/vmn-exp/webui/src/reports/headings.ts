export interface Heading {
  depth: number;
  text: string;
  slug: string;
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-");
}

export function makeSlugger(): (text: string) => string {
  const seen = new Map<string, number>();
  return (text) => {
    const base = slugify(text) || "section";
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return n === 0 ? base : `${base}-${n}`;
  };
}

function stripInline(text: string): string {
  return text
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_`~]/g, "")
    .replace(/\s+#+\s*$/, "")
    .trim();
}

const SETEXT = /^ {0,3}(=+|-+)\s*$/;
const ATX = /^ {0,3}(#{1,6})\s+(.*)$/;

function isParagraphLine(line: string | undefined): line is string {
  return !!line && line.trim() !== "" && !/^ {0,3}([#>*+-]|\d+[.)]|\|)/.test(line);
}

/** ATX and setext headings outside fenced code blocks, in document order. */
export function extractHeadings(source: string): Heading[] {
  const slug = makeSlugger();
  const out: Heading[] = [];
  const push = (depth: number, raw: string) => {
    const text = stripInline(raw);
    out.push({ depth, text, slug: slug(text) });
  };
  let fence: string | null = null;
  let prev: string | undefined;
  for (const line of source.split("\n")) {
    const f = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (f) {
      if (fence === null) fence = f[1][0];
      else if (f[1][0] === fence) fence = null;
      prev = undefined;
      continue;
    }
    if (fence !== null) continue;
    const h = line.match(ATX);
    const st = line.match(SETEXT);
    if (h) push(h[1].length, h[2]);
    else if (st && isParagraphLine(prev)) {
      push(st[1][0] === "=" ? 1 : 2, prev);
      prev = undefined;
      continue;
    }
    prev = h ? undefined : line;
  }
  return out;
}
