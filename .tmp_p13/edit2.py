import os
os.chdir("/Users/pavelr/projects/vmn/.claude/worktrees/wf_d6897350-c89-7/packages/vmn-exp/webui/src/pages")
p = "Report.tsx"
s = open(p).read()
pairs = [
    ('import { useQuery } from "@tanstack/react-query";',
     'import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";'),
    ('import ReportHistory from "../reports/ReportHistory";',
     'import ReportHistory from "../reports/ReportHistory";\n'
     'import { PanelCaptureProvider, usePanelCapture } from "../reports/publishedData";'),
    ('''function ReportBody(''', '''/** The published revision renders frozen panels unless the editor is on it. */
function isFrozen(report: ReportDetail, rev: number, params: URLSearchParams): boolean {
  if (rev !== report.published_rev || params.get("live") === "1") return false;
  return !(report.can_edit && rev === report.rev);
}

function PublishButton({ ws, report }: { ws: string; report: ReportDetail }) {
  const capture = usePanelCapture();
  const client = useQueryClient();
  const publish = useMutation({
    mutationFn: () => apiReports.publish(ws, report.rid, { rev: report.rev, data: capture?.collect() ?? {} }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["report", ws, report.rid] }),
  });
  return (
    <span>
      <button type="button" className="btn btn-sm" disabled={publish.isPending} onClick={() => publish.mutate()}>
        Publish
      </button>
      {publish.error && <span className="error"> {(publish.error as Error).message}</span>}
    </span>
  );
}

function ReportBody('''),
    ('''  const target = commentTarget.report(report.rid);
  const renderPanel''', '''  const target = commentTarget.report(report.rid);
  const published = isFrozen(report, rev, params) ? { rid: report.rid, rev } : undefined;
  const renderPanel'''),
    ('<Panel ws={ws} spec={spec} />', '<Panel ws={ws} spec={spec} published={published} />'),
    ('''  return (
    <>
      <PublishedBanner''', '''  return (
    <PanelCaptureProvider>
      <PublishedBanner'''),
    ('''<div className="muted" style={{ marginBottom: 8 }}>v{rev}{rev === report.rev ? " (latest)" : ""}</div>''',
     '''<div className="muted" style={{ marginBottom: 8 }}>
        v{rev}{rev === report.rev ? " (latest)" : ""}{" "}
        {report.can_edit && rev === report.rev && <PublishButton ws={ws} report={report} />}
      </div>'''),
    ('''        <Comments ws={ws} target={target} />
      </div>
    </>
  );''', '''        <Comments ws={ws} target={target} />
      </div>
    </PanelCaptureProvider>
  );'''),
]
for a, b in pairs:
    assert a in s, a
    s = s.replace(a, b)
open(p, "w").write(s)
