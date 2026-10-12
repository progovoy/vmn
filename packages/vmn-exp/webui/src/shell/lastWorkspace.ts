/** The workspace last opened in this tab, so global routes (`/tokens`) keep
 *  their context. */
import { LAST_WS_KEY } from "./contracts";

export const lastWorkspace = (): string | null => sessionStorage.getItem(LAST_WS_KEY);

export function rememberWorkspace(ws: string): void {
  sessionStorage.setItem(LAST_WS_KEY, ws);
}
