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

/** ATX headings outside fenced code blocks, in document order. */
export function extractHeadings(source: string): Heading[] {
  const slug = makeSlugger();
  const out: Heading[] = [];
  let fence: string | null = null;
  for (const line of source.split("\n")) {
    const f = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (f) {
      if (fence === null) fence = f[1][0];
      else if (f[1][0] === fence) fence = null;
      continue;
    }
    if (fence !== null) continue;
    const h = line.match(/^ {0,3}(#{1,6})\s+(.*)$/);
    if (h) {
      const text = stripInline(h[2]);
      out.push({ depth: h[1].length, text, slug: slug(text) });
    }
  }
  return out;
}
