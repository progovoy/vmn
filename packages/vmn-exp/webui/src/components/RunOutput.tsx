import ArtifactPreview from "./ArtifactPreview";
import type { Artifact } from "../util/artifactTree";

/** The console output `vmn-exp run` (or `start_run(capture_output=True)`)
 *  kept as the run's `output.log` artifact. */
export const OUTPUT_LOG = "output.log";

export default function RunOutput({ artifacts, downloadUrl }: {
  artifacts: Artifact[]; downloadUrl: (filename: string) => string;
}) {
  const output = artifacts.find((a) => a.name === OUTPUT_LOG);
  if (!output) return null;
  return (
    <div className="card">
      <div className="eyebrow">output</div>
      <ArtifactPreview artifact={output} url={downloadUrl(OUTPUT_LOG)} />
    </div>
  );
}
