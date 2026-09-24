/** Run tags: parsing the editor's `key=value` input and applying an edit.
 *  The rules mirror the server's exp_tag checks, so a refused tag never
 *  costs a request. */
export type Tags = Record<string, string>;

const MAX_KEY = 64;
const MAX_VALUE = 256;
// Printable, no leading "-" (it would parse as a flag).
const PRINTABLE = /^\P{C}*$/u;

export function parseTag(text: string): { key: string; value: string } | null {
  const trimmed = text.trim();
  const eq = trimmed.indexOf("=");
  const key = (eq < 0 ? trimmed : trimmed.slice(0, eq)).trim();
  const value = eq < 0 ? "" : trimmed.slice(eq + 1).trim();
  if (!key || key.length > MAX_KEY || /\s/.test(key) || key.startsWith("-")) return null;
  if (value.length > MAX_VALUE || value.startsWith("-")) return null;
  if (!PRINTABLE.test(key) || !PRINTABLE.test(value)) return null;
  return { key, value };
}

export function applyTagEdit(tags: Tags | undefined, set: Tags, remove: string[]): Tags {
  const next: Tags = { ...(tags ?? {}), ...set };
  remove.forEach((k) => delete next[k]);
  return next;
}
