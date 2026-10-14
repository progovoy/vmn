/** A route element under the app's selection tray, as the shell mounts it
 *  (SelectionTrayHost) for the route's `:ws`/`:app`. */
import type { ReactNode } from "react";
import { useParams } from "react-router-dom";
import SelectionTrayHost from "../SelectionTrayHost";

export function WithTray({ children }: { children: ReactNode }) {
  const { ws, app } = useParams();
  return <SelectionTrayHost ws={ws} app={app}>{children}</SelectionTrayHost>;
}
