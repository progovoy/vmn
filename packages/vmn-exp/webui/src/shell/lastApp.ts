/** The app last opened in each workspace of this tab, so workspace pages
 *  (Models, Reports) keep the sidebar's app context (plan 20 E2). */
import { appHref } from "../util";
import { appName } from "../api";
import { LAST_APP_KEY, type ShellContext } from "./contracts";

function lastApps(): Record<string, string> {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(LAST_APP_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? parsed as Record<string, string> : {};
  } catch {
    return {};
  }
}

export const lastApp = (ws: string): string | undefined => lastApps()[ws];

export function rememberApp(ws: string, appTag: string): void {
  sessionStorage.setItem(LAST_APP_KEY, JSON.stringify({ ...lastApps(), [ws]: appTag }));
}

/** *ctx* with the workspace's last app filled in when the URL names none. */
export function withLastApp(ctx: ShellContext): ShellContext {
  if (ctx.appTag || !ctx.ws || !ctx.workspace) return ctx;
  const tag = lastApp(ctx.ws);
  if (!tag) return ctx;
  const app = appName(tag);
  return { ...ctx, appTag: tag, app, appBase: appHref(ctx.ws, app) };
}
