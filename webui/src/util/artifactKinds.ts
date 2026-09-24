/** How an artifact can be previewed, judged by its file extension. */
export type ArtifactKind = "image" | "table" | "text" | "binary";

/** The most of a text artifact a preview fetches and shows. */
export const TEXT_PREVIEW_BYTES = 200 * 1024;
/** Data rows a table preview shows (after the header). */
export const TABLE_PREVIEW_ROWS = 100;

const IMAGE = new Set(["png", "jpg", "jpeg", "gif", "svg", "webp"]);
const TABLE = new Set(["csv", "tsv"]);
const TEXT = new Set([
  "json", "jsonl", "yaml", "yml", "txt", "log", "md", "toml", "ini", "cfg",
  "xml", "html", "py", "sh", "out", "err",
]);

export const extensionOf = (name: string) => {
  const base = name.slice(name.lastIndexOf("/") + 1);
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : "";
};

export function artifactKind(name: string): ArtifactKind {
  const ext = extensionOf(name);
  if (IMAGE.has(ext)) return "image";
  if (TABLE.has(ext)) return "table";
  if (TEXT.has(ext)) return "text";
  return "binary";
}

/** Rows of a CSV/TSV: quoted cells may hold the delimiter, newlines and
 *  doubled quotes. Parsing stops once *maxRows* rows are complete. */
export function parseDelimited(text: string, delim: string, maxRows = Infinity): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  const endRow = () => { row.push(cell); rows.push(row); row = []; cell = ""; };
  for (let i = 0; i < text.length && rows.length < maxRows; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"' && cell === "") quoted = true;
    else if (c === delim) { row.push(cell); cell = ""; }
    else if (c === "\n") endRow();
    else if (c !== "\r") cell += c;
  }
  if (rows.length < maxRows && (cell !== "" || row.length > 0)) endRow();
  return rows;
}

export function truncateText(text: string, limit = TEXT_PREVIEW_BYTES) {
  return text.length > limit
    ? { text: text.slice(0, limit), truncated: true }
    : { text, truncated: false };
}
