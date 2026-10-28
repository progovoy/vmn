/** An app's store settings (plan 28 A0): GET/PUT `.../apps/{app}/settings`,
 *  the YAML as written plus what it parses to and who saved it last. A PUT
 *  the server refuses (bad YAML or key) is a 400 whose message says why. */
import { appTag, get, put } from "./http";

export interface AppSettings {
  text: string;
  settings: Record<string, unknown>;
  /** Why the stored file does not parse, else null. */
  error: string | null;
  updated_at?: string;
  updated_by?: { id?: string; name?: string };
}

const path = (ws: string, app: string) =>
  `/workspaces/${encodeURIComponent(ws)}/apps/${encodeURIComponent(appTag(app))}/settings`;

export const apiSettings = {
  get: (ws: string, app: string) => get<AppSettings>(path(ws, app)),
  save: (ws: string, app: string, text: string) => put<AppSettings>(path(ws, app), { text }),
};
