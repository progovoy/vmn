import { useEffect } from "react";

export const DRAFT_SAVE_MS = 3000;

export interface Draft { body: string; base: number }

export const draftKey = (ws: string, rid: string) => `vmn_report_draft:${ws}/${rid}`;

export function loadDraft(key: string): Draft | null {
  try {
    const d = JSON.parse(localStorage.getItem(key) ?? "null");
    return d && typeof d.body === "string" && typeof d.base === "number" ? d : null;
  } catch {
    return null;
  }
}

export const clearDraft = (key: string) => localStorage.removeItem(key);

/** Write the unsaved body a few seconds after the last edit. */
export function useDraftAutosave(key: string, draft: Draft | null) {
  const body = draft?.body;
  const base = draft?.base;
  useEffect(() => {
    if (body === undefined || base === undefined) return;
    const t = setTimeout(() => localStorage.setItem(key, JSON.stringify({ body, base })), DRAFT_SAVE_MS);
    return () => clearTimeout(t);
  }, [key, body, base]);
}
