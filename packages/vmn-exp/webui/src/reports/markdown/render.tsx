// Renders the in-house markdown AST (ast.ts) to React elements. Nothing is
// ever injected as HTML, so raw HTML in a report is always shown as text.
import type { ReactNode } from "react";
import { inlineText, type Block, type Inline } from "./ast";

export interface RenderOptions {
  resolveMedia?: (uri: string) => string;
  /** Renders a ```vmn-panel fenced block from its raw text. */
  renderPanelBlock: (raw: string) => ReactNode;
  /** Heading id for the n-th heading of the document. */
  headingId: (index: number, text: string) => string;
}

const SAFE_HREF = /^(https?:|mailto:|#|\/|\.|vmn:\/\/|[^:]*$)/i;

function link(href: string, children: ReactNode, key: number) {
  if (!SAFE_HREF.test(href)) return <span key={key}>{children}</span>;
  if (href.startsWith("#")) return <a key={key} href={href}>{children}</a>;
  return (
    <a key={key} href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

function image(src: string, alt: string, key: number, opts: RenderOptions) {
  if (src.startsWith("vmn://") && opts.resolveMedia) {
    return <img key={key} src={opts.resolveMedia(src)} alt={alt} />;
  }
  return link(src, alt || src, key);
}

function inlines(nodes: Inline[], opts: RenderOptions): ReactNode[] {
  return nodes.map((n, i) => {
    switch (n.type) {
      case "text":
        return n.value;
      case "code":
        return <code key={i}>{n.value}</code>;
      case "break":
        return <br key={i} />;
      case "emphasis":
        return <em key={i}>{inlines(n.children, opts)}</em>;
      case "strong":
        return <strong key={i}>{inlines(n.children, opts)}</strong>;
      case "delete":
        return <del key={i}>{inlines(n.children, opts)}</del>;
      case "link":
        return link(n.href, inlines(n.children, opts), i);
      case "image":
        return image(n.src, n.alt, i, opts);
    }
  });
}

interface Ctx {
  opts: RenderOptions;
  heading: number;
}

function table(b: Extract<Block, { type: "table" }>, key: number, ctx: Ctx) {
  const align = (i: number) => (b.align[i] ? { textAlign: b.align[i]! } : undefined);
  return (
    <table key={key}>
      <thead>
        <tr>
          {b.head.map((c, i) => (
            <th key={i} style={align(i)}>{inlines(c, ctx.opts)}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {b.rows.map((r, ri) => (
          <tr key={ri}>
            {r.map((c, i) => (
              <td key={i} style={align(i)}>{inlines(c, ctx.opts)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function listItem(blocks: Block[], tight: boolean, key: number, ctx: Ctx) {
  const content = tight
    ? blocks.map((b, i) => (b.type === "paragraph" ? <span key={i}>{inlines(b.children, ctx.opts)}</span> : block(b, i, ctx)))
    : blocks.map((b, i) => block(b, i, ctx));
  return <li key={key}>{content}</li>;
}

function block(b: Block, key: number, ctx: Ctx): ReactNode {
  switch (b.type) {
    case "heading": {
      const Tag = `h${b.depth}` as "h1";
      const id = ctx.opts.headingId(ctx.heading++, inlineText(b.children));
      return <Tag key={key} id={id}>{inlines(b.children, ctx.opts)}</Tag>;
    }
    case "paragraph":
      return <p key={key}>{inlines(b.children, ctx.opts)}</p>;
    case "code":
      if (b.lang === "vmn-panel") return <div key={key}>{ctx.opts.renderPanelBlock(b.value)}</div>;
      return (
        <pre key={key}>
          <code className={b.lang ? `language-${b.lang}` : undefined}>{b.value}</code>
        </pre>
      );
    case "blockquote":
      return <blockquote key={key}>{b.children.map((c, i) => block(c, i, ctx))}</blockquote>;
    case "list": {
      const items = b.items.map((it, i) => listItem(it, b.tight, i, ctx));
      return b.ordered ? <ol key={key} start={b.start === 1 ? undefined : b.start}>{items}</ol> : <ul key={key}>{items}</ul>;
    }
    case "table":
      return table(b, key, ctx);
    case "hr":
      return <hr key={key} />;
  }
}

export function renderBlocks(blocks: Block[], opts: RenderOptions): ReactNode[] {
  const ctx: Ctx = { opts, heading: 0 };
  return blocks.map((b, i) => block(b, i, ctx));
}

/** Every heading in document order (nested ones included), for the TOC. */
export function collectHeadings(blocks: Block[]): { depth: number; text: string }[] {
  const out: { depth: number; text: string }[] = [];
  const walk = (bs: Block[]) =>
    bs.forEach((b) => {
      if (b.type === "heading") out.push({ depth: b.depth, text: inlineText(b.children) });
      else if (b.type === "blockquote") walk(b.children);
      else if (b.type === "list") b.items.forEach(walk);
    });
  walk(blocks);
  return out;
}
