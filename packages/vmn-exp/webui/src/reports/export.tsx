/** Entry of the exported-report bundle (plan 13 §6): renders one report
 *  revision from data inlined into the page, without any network. */
import "../styles.css";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { Markdown } from "./Markdown";
import Panel from "./Panel";
import { MediaUrlContext, type MediaUrl } from "./mediaUrl";
import type { PanelPayload } from "./publishedData";

export interface ExportData {
  title: string;
  rev: number;
  body: string;
  /** Published payload per panel id. */
  panels: Record<string, PanelPayload>;
  /** `vmn://<app>/<verstr>/<path>` -> data URI, for media within the cap. */
  media: Record<string, string>;
  /** The media left out, each with why. */
  skipped?: Record<string, "missing" | "over_cap">;
  /** The cap `over_cap` media went over (`--max-media-mb`). */
  max_media_mb?: number;
}

const DATA_ID = "vmn-report-data";

/** An image that says, in its own pixels, why the export has no file. */
function noteImage(note: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="48"><rect width="100%" height="100%" `
    + `fill="#f2f2f2" stroke="#999" stroke-dasharray="4"/><text x="50%" y="50%" text-anchor="middle" `
    + `dominant-baseline="middle" font-family="sans-serif" font-size="13" fill="#555">${note}</text></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function skippedNote(data: ExportData, uri: string): string {
  const why = data.skipped?.[uri];
  const reason = why === "over_cap" ? ` (over ${data.max_media_mb} MB)` : why === "missing" ? " (file missing)" : "";
  return `not included in export${reason}`;
}

export function ExportedReport({ data }: { data: ExportData }) {
  const resolveMedia = (uri: string) => data.media[uri] ?? noteImage(skippedNote(data, uri));
  const mediaUrl: MediaUrl = (_ws, app, verstr, path) => resolveMedia(`vmn://${app}/${verstr}/${path}`);
  return (
    <MemoryRouter>
      <MediaUrlContext.Provider value={mediaUrl}>
        <Markdown source={data.body} resolveMedia={resolveMedia}
          renderPanel={(spec) => <Panel ws="" spec={spec} payload={data.panels[String(spec.id ?? "")] ?? null} />} />
      </MediaUrlContext.Provider>
    </MemoryRouter>
  );
}

export function mountExport(doc: Document) {
  const data = JSON.parse(doc.getElementById(DATA_ID)!.textContent!) as ExportData;
  createRoot(doc.getElementById("root")!).render(<ExportedReport data={data} />);
}

if (typeof document !== "undefined" && document.getElementById(DATA_ID)?.textContent) mountExport(document);
