/** Reports and comments API (plan 13 §8.1), all under /workspaces/{ws}. */
import { appTag, del, get, patch, post } from "./http";

export interface ReportRow {
  rid: string;
  title?: string;
  created_at?: string | null;
  created_by?: string | null;
  updated_at?: string | null;
  author?: string | null;
  rev: number;
  published_rev?: number | null;
  published_at?: string | null;
  archived?: boolean;
  pinned?: boolean;
}

export interface RevisionMeta {
  rev: number;
  author?: string | null;
  created_at?: string | null;
  message?: string | null;
}

export interface ReportDetail extends ReportRow {
  body: string;
  revisions?: RevisionMeta[];
  /** Set by the server when the caller may edit (editors land on the draft). */
  can_edit?: boolean;
}

export interface Revision extends RevisionMeta {
  body: string;
  data?: string[];
}

export type CommentAnchor = { metric?: string; step?: number; panel?: string };

export interface Comment {
  id: string;
  ts?: string | null;
  author?: string | null;
  text: string | null;
  reply_to?: string | null;
  anchor?: CommentAnchor | null;
  resolved: boolean;
  deleted: boolean;
}

/** `me` is the caller's identity when the server knows it; without it
 *  (standalone token = admin) every comment is editable. */
export interface CommentThread {
  comments: Comment[];
  me?: string | null;
}

export interface NewComment {
  target: string;
  text: string;
  reply_to?: string;
  anchor?: CommentAnchor;
}

export const commentTarget = {
  run: (app: string, verstr: string) => `run:${app}:${verstr}`,
  report: (rid: string) => `report:${rid}`,
};

const ws_ = (ws: string) => `/workspaces/${encodeURIComponent(ws)}`;
const rep = (ws: string, rid: string) => `${ws_(ws)}/reports/${encodeURIComponent(rid)}`;
const cmt = (ws: string, target: string, id: string) =>
  `${ws_(ws)}/comments/${encodeURIComponent(target)}/${encodeURIComponent(id)}`;

export const apiReports = {
  listReports: (ws: string, archived = false) =>
    get<{ reports: ReportRow[] }>(`${ws_(ws)}/reports?archived=${archived}`),
  /** Reports whose panels show *app* (or, with *verstr*, that run). */
  reportsUsing: (ws: string, app: string, verstr?: string) =>
    get<{ reports: ReportRow[] }>(
      `${ws_(ws)}/apps/${appTag(app)}/reports${verstr ? `?verstr=${encodeURIComponent(verstr)}` : ""}`,
    ),
  getReport: (ws: string, rid: string) => get<ReportDetail>(rep(ws, rid)),
  getRevision: (ws: string, rid: string, n: number) => get<Revision>(`${rep(ws, rid)}/revisions/${n}`),
  getPanelData: (ws: string, rid: string, n: number, panel: string) =>
    get<unknown>(`${rep(ws, rid)}/revisions/${n}/data/${encodeURIComponent(panel)}`),
  createReport: (ws: string, body: { title: string; body: string }) =>
    post<{ rid: string; rev: number }>(`${ws_(ws)}/reports`, body),
  saveRevision: (ws: string, rid: string, body: { base: number; body: string; message?: string }) =>
    post<{ rev: number }>(`${rep(ws, rid)}/revisions`, body),
  publish: (ws: string, rid: string, body: { rev: number; data: Record<string, unknown> }) =>
    post<unknown>(`${rep(ws, rid)}/publish`, body),
  patchReport: (ws: string, rid: string, body: { title?: string; archived?: boolean; pinned?: boolean }) =>
    patch<unknown>(rep(ws, rid), body),
  deleteReport: (ws: string, rid: string) => del(rep(ws, rid)),
  listComments: (ws: string, target: string) =>
    get<CommentThread>(`${ws_(ws)}/comments?target=${encodeURIComponent(target)}`),
  addComment: (ws: string, body: NewComment) => post<{ id: string }>(`${ws_(ws)}/comments`, body),
  editComment: (ws: string, target: string, id: string, body: { text?: string; resolved?: boolean }) =>
    patch<unknown>(cmt(ws, target, id), body),
  deleteComment: (ws: string, target: string, id: string) => del(cmt(ws, target, id)),
};
