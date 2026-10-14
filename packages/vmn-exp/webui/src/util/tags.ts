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

/** How a tag reads on a chip: `key: value`, or just the key. */
export const tagLabel = (key: string, value: string) => (value ? `${key}: ${value}` : key);

export function applyTagEdit(tags: Tags | undefined, set: Tags, remove: string[]): Tags {
  const next: Tags = { ...(tags ?? {}), ...set };
  remove.forEach((k) => delete next[k]);
  return next;
}

export interface TagEdit { set: Tags; remove: string[] }

const entries = (text: string, sep: RegExp) => text.split(sep).map((s) => s.trim()).filter(Boolean);

/** A bulk tag edit: `key=value` entries (comma or line separated) to set and
 *  keys (comma or space separated) to remove; else the first problem. */
export function parseTagEdit(setText: string, removeText: string): { edit: TagEdit } | { error: string } {
  const set: Tags = {};
  for (const entry of entries(setText, /[,\n]/)) {
    const tag = parseTag(entry);
    if (!tag) return { error: `"${entry}": use key=value (no spaces in key, no leading -)` };
    set[tag.key] = tag.value;
  }
  const remove = entries(removeText, /[,\s]/);
  const bad = remove.find((k) => k.includes("=") || parseTag(k)?.key !== k);
  if (bad !== undefined) return { error: `"${bad}" is not a tag key` };
  if (!Object.keys(set).length && !remove.length) return { error: "Add a tag to set or a key to remove" };
  return { edit: { set, remove } };
}
