/** A board's Views menu: my views (localStorage) under the app's team views
 *  for *page* (plan 28 P4, from the app's status), the page's default team
 *  view applied on first landing (useDefaultView), and for an editor "Save
 *  for team", written into the app's settings (`ui.views`) through the
 *  settings PUT — the file is rewritten from its parsed form, so YAML
 *  comments do not survive it. */
import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { apiSettings } from "../apiSettings";
import { useDefaultView } from "../hooks/useDefaultView";
import { usePageScope } from "../shell/usePageScope";
import { useAppStatus } from "../shell/useShellData";
import { viewSearch } from "../util/savedViews";
import { pageViews, placedSearch, withTeamView, type ViewPage } from "../util/teamViews";
import { dumpYaml } from "../util/yamlDump";
import SavedViews from "./SavedViews";

export default function BoardViews({ ws, app, page, job, onViewApplied }: {
  ws: string;
  /** The app in URL tag form. */
  app: string;
  page: ViewPage;
  /** An outer run's page (its verstr): my views of its own. */
  job?: string;
  /** A view replaced the URL: controls holding their own state reset. */
  onViewApplied: () => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const client = useQueryClient();
  const status = useAppStatus(ws, app).data;
  const views = status ? status.views ?? [] : undefined;
  const scope = usePageScope(ws);

  const go = useCallback((search: string) => {
    navigate({ search }, { replace: true });
    onViewApplied();
  }, [navigate, onViewApplied]);
  const applyTeam = useCallback((search: string) => go(placedSearch(location.search, search)), [go, location.search]);
  useDefaultView(`${ws}/${app}/${page}${job ? `/${job}` : ""}`, views, page, applyTeam);

  const saveTeam = async (name: string, isDefault: boolean) => {
    const current = await apiSettings.get(ws, app);
    if (current.error) throw new Error(`The app's settings are invalid (${current.error}): fix them on its settings page first`);
    const view = { name, page, search: viewSearch(location.search), default: isDefault };
    await apiSettings.save(ws, app, dumpYaml(withTeamView(current.settings, view)));
    await Promise.all([
      client.invalidateQueries({ queryKey: ["app-status", ws, app] }),
      client.invalidateQueries({ queryKey: ["app-settings", ws] }),
    ]);
  };

  return (
    <SavedViews
      ws={ws} app={job ? `${app}/run/${job}` : app} search={location.search} onApply={go}
      team={pageViews(views, page)} onApplyTeam={applyTeam}
      onSaveTeam={scope.metaStatus === "ok" && !scope.readOnly ? saveTeam : undefined}
    />
  );
}
