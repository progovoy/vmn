import { useMemo, type ReactNode } from "react";
import Panel from "./Panel";
import { makeSlugger, type Heading } from "./headings";
import { parseBlocks } from "./markdown/block";
import { collectHeadings, renderBlocks } from "./markdown/render";
import { parseYamlLite } from "./yamlLite";

export type PanelSpec = Record<string, unknown>;

export interface MarkdownProps {
  source: string;
  resolveMedia?: (uri: string) => string;
  renderPanel?: (spec: PanelSpec, rawText: string) => ReactNode;
  /** Workspace the report's panels fetch from; without it (and no
   *  renderPanel) panels render as placeholders. */
  ws?: string;
}

const TOC_MIN_HEADINGS = 4;

/** A panel block is YAML (a JSON object is valid too). */
function parseSpec(raw: string): unknown {
  const text = raw.trim();
  return text.startsWith("{") ? JSON.parse(text) : parseYamlLite(raw);
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
    spec = parseSpec(raw);
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

function panelRenderer(props: MarkdownProps): MarkdownProps["renderPanel"] {
  const { ws } = props;
  if (props.renderPanel || ws === undefined) return props.renderPanel;
  return (spec) => <Panel ws={ws} spec={spec} />;
}

export function Markdown(props: MarkdownProps) {
  const { source, resolveMedia } = props;
  const blocks = useMemo(() => parseBlocks(source), [source]);
  const headings: Heading[] = useMemo(() => {
    const slug = makeSlugger();
    return collectHeadings(blocks).map((h) => ({ ...h, slug: slug(h.text) }));
  }, [blocks]);
  const renderPanel = panelRenderer(props);
  const body = renderBlocks(blocks, {
    resolveMedia,
    renderPanelBlock: (raw) => <PanelBlock raw={raw} renderPanel={renderPanel} />,
    headingId: (i, text) => headings[i]?.slug ?? makeSlugger()(text),
  });
  return (
    <div className="md-body">
      {headings.length >= TOC_MIN_HEADINGS && <TableOfContents headings={headings} />}
      {body}
    </div>
  );
}
