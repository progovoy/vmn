// AST of the in-house markdown parser (block.ts + inline.ts), rendered by
// render.tsx. Raw HTML never gets a node of its own: it stays text.

export type Inline =
  | { type: "text"; value: string }
  | { type: "code"; value: string }
  | { type: "break" }
  | { type: "emphasis" | "strong" | "delete"; children: Inline[] }
  | { type: "link"; href: string; children: Inline[] }
  | { type: "image"; src: string; alt: string };

export type Align = "left" | "center" | "right" | null;

export type Block =
  | { type: "heading"; depth: number; children: Inline[] }
  | { type: "paragraph"; children: Inline[] }
  | { type: "code"; lang: string; value: string }
  | { type: "blockquote"; children: Block[] }
  | { type: "list"; ordered: boolean; start: number; tight: boolean; items: Block[][] }
  | { type: "table"; align: Align[]; head: Inline[][]; rows: Inline[][][] }
  | { type: "hr" };

/** Plain text of inline nodes (headings' slugs, image alt text). */
export function inlineText(nodes: Inline[]): string {
  return nodes
    .map((n) => {
      if (n.type === "text" || n.type === "code") return n.value;
      if (n.type === "image") return n.alt;
      if (n.type === "break") return " ";
      return inlineText(n.children);
    })
    .join("");
}
