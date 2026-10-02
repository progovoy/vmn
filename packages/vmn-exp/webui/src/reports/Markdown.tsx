import { useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { parse as parseYaml } from "yaml";
import { extractHeadings, makeSlugger, type Heading } from "./headings";

export type PanelSpec = Record<string, unknown>;

export interface MarkdownProps {
  source: string;
  resolveMedia?: (uri: string) => string;
  renderPanel?: (spec: PanelSpec, rawText: string) => ReactNode;
}

const TOC_MIN_HEADINGS = 4;

interface MdNode {
  type: string;
  depth?: number;
  value?: string;
  children?: MdNode[];
  data?: { hProperties?: Record<string, unknown> };
}

function nodeText(node: MdNode): string {
  if (node.value !== undefined) return node.value;
  return (node.children ?? []).map(nodeText).join("");
}

/** Remark plugin: give headings ids matching the precomputed TOC slugs. */
function remarkHeadingIds(headings: Heading[]) {
  return () => (tree: MdNode) => {
    const fallback = makeSlugger();
    let i = 0;
    const walk = (node: MdNode) => {
      if (node.type === "heading") {
        const id = headings[i]?.slug ?? fallback(nodeText(node));
        i += 1;
        node.data = { ...node.data, hProperties: { ...node.data?.hProperties, id } };
      }
      node.children?.forEach(walk);
    };
    walk(tree);
  };
}

function PlaceholderPanel({ spec }: { spec: PanelSpec }) {
  return (
    <div className="md-panel md-panel-placeholder">
      Panel {String(spec.id ?? "?")} ({String(spec.type ?? "unknown")})
    </div>
  );
}

function PanelBlock({ raw, renderPanel }: { raw: string; renderPanel?: MarkdownProps["renderPanel"] }) {
  let spec: unknown;
  try {
    spec = parseYaml(raw);
  } catch (e) {
    return <PanelError message={(e as Error).message} />;
  }
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) {
    return <PanelError message="panel spec must be a mapping" />;
  }
  const s = spec as PanelSpec;
  return <>{renderPanel ? renderPanel(s, raw) : <PlaceholderPanel spec={s} />}</>;
}

function PanelError({ message }: { message: string }) {
  return (
    <div role="alert" className="md-panel md-panel-error">
      Invalid panel: {message}
    </div>
  );
}

export function TableOfContents({ headings }: { headings: Heading[] }) {
  return (
    <nav aria-label="Table of contents" className="md-toc">
      <ul>
        {headings.map((h) => (
          <li key={h.slug} style={{ marginLeft: `${(h.depth - 1) * 12}px` }}>
            <a href={`#${h.slug}`}>{h.text}</a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function buildComponents(props: MarkdownProps): Components {
  return {
    a: ({ node: _n, ...rest }) =>
      rest.href?.startsWith("#") ? <a {...rest} /> : <a {...rest} target="_blank" rel="noopener noreferrer" />,
    img: ({ src, alt }) => {
      if (src?.startsWith("vmn://") && props.resolveMedia) {
        return <img src={props.resolveMedia(src)} alt={alt ?? ""} />;
      }
      return (
        <a href={src} target="_blank" rel="noopener noreferrer">
          {alt || src}
        </a>
      );
    },
    pre: ({ node, children }) => {
      const code = node?.children[0];
      const classes = code && "properties" in code ? code.properties.className : undefined;
      if (Array.isArray(classes) && classes.includes("language-vmn-panel")) {
        const raw = code && "children" in code ? code.children.map((c) => ("value" in c ? c.value : "")).join("") : "";
        return <PanelBlock raw={raw} renderPanel={props.renderPanel} />;
      }
      return <pre>{children}</pre>;
    },
  };
}

export function Markdown(props: MarkdownProps) {
  const { source } = props;
  const headings = useMemo(() => extractHeadings(source), [source]);
  const plugins = useMemo(() => [remarkGfm, remarkHeadingIds(headings)], [headings]);
  const components = useMemo(() => buildComponents(props), [props.resolveMedia, props.renderPanel]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="md-body">
      {headings.length >= TOC_MIN_HEADINGS && <TableOfContents headings={headings} />}
      <ReactMarkdown remarkPlugins={plugins} components={components} urlTransform={urlTransform}>
        {source}
      </ReactMarkdown>
    </div>
  );
}

/** Keep vmn:// image refs (the default transform strips unknown schemes). */
function urlTransform(url: string): string {
  if (url.startsWith("vmn://")) return url;
  return /^(https?:|mailto:|#|\/|\.|[^:]*$)/i.test(url) ? url : "";
}
