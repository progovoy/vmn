/** An app's store settings (plan 28 A0): the YAML a store workspace reads
 *  in place of conf.yml's `experiment:` block (metric goals, `ui.*`). An
 *  editor saves it; the server refuses invalid settings with the reason,
 *  shown here with the edit kept. Viewers and read-only servers only read. */
import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { appName as toAppName } from "../api";
import { apiSettings, type AppSettings } from "../apiSettings";
import { PageHead, Skeleton } from "../components/ui";
import { usePageScope } from "../shell/usePageScope";
import { relTime } from "../util";

const PLACEHOLDER = "metrics:\n  loss: {goal: min, primary: true}\nui:\n  group_aggregate: best\n";

function SavedBy({ settings }: { settings: AppSettings }) {
  if (!settings.updated_at) return <div className="muted">Not saved yet: conf.yml and the runs' own declarations apply.</div>;
  const who = settings.updated_by?.name || settings.updated_by?.id;
  return (
    <div className="muted" title={settings.updated_at}>
      Saved {relTime(settings.updated_at)}{who ? ` by ${who}` : ""}
    </div>
  );
}

function SettingsForm({ ws, app, saved, readOnlyReason }: {
  ws: string; app: string; saved: AppSettings; readOnlyReason: string | null;
}) {
  const client = useQueryClient();
  const [text, setText] = useState(saved.text);
  useEffect(() => setText(saved.text), [saved.text]);
  const save = useMutation({
    mutationFn: () => apiSettings.save(ws, app, text),
    onSuccess: (next) => client.setQueryData(["app-settings", ws, app], next),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const edited = text !== saved.text;
  return (
    <form className="card" onSubmit={submit}>
      <label className="field">
        <span>Settings YAML</span>
        <textarea
          className="mono" rows={16} spellCheck={false} value={text} placeholder={PLACEHOLDER}
          readOnly={readOnlyReason !== null}
          onChange={(e) => { setText(e.target.value); save.reset(); }}
        />
      </label>
      {save.error && <div className="error" role="alert">{save.error.message}</div>}
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 10 }}>
        {readOnlyReason === null ? (
          <button type="submit" disabled={!edited || save.isPending}>Save</button>
        ) : <span className="muted">{readOnlyReason}</span>}
        {save.isSuccess && !edited && <span className="muted">Saved</span>}
        <SavedBy settings={saved} />
      </div>
    </form>
  );
}

export default function AppSettingsPage() {
  const { ws, app: tag } = useParams() as { ws: string; app: string };
  const app = toAppName(tag);
  const { readOnlyReason } = usePageScope(ws);
  const query = useQuery({ queryKey: ["app-settings", ws, app], queryFn: () => apiSettings.get(ws, app) });
  return (
    <>
      <PageHead title={app} what="settings" />
      <p className="muted">
        What this app reads in place of conf.yml&apos;s <code>experiment:</code> block in a store
        workspace (below conf.yml in a checkout): <code>metrics.&lt;name&gt;</code> goals, summaries,
        primary and hidden, and <code>ui.*</code>.
      </p>
      {query.data?.error && (
        <div className="error" role="alert">The saved settings are ignored: {query.data.error}</div>
      )}
      {query.data ? (
        <SettingsForm ws={ws} app={app} saved={query.data} readOnlyReason={readOnlyReason} />
      ) : query.error ? <div className="error">{String(query.error)}</div> : <Skeleton />}
    </>
  );
}
