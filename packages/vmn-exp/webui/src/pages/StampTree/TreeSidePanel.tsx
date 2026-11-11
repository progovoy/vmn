import { ConfigSection } from "./ConfigSection";
import { isPrerelease, MODE_COLOR, type Edge, type Node } from "./layout";
import { VersionDetails } from "./VersionDetails";

function ModeDot({ mode }: { mode: string }) {
  const color = MODE_COLOR[mode] ?? "var(--text-muted)";
  return (
    <span
      style={{
        width: 10, height: 10, borderRadius: "50%", display: "inline-block",
        flexShrink: 0,
        background: isPrerelease(mode) ? "transparent" : color,
        border: `2px solid ${color}`,
      }}
    />
  );
}

/** The selected version's details, its config and the release-mode legend. */
export function TreeSidePanel({
  ws, app, current, canonical, edges, olderVerstrs, presentModes, onSelect,
}: {
  ws: string;
  app: string;
  current: Node;
  canonical: Map<string, string>;
  edges: Edge[];
  olderVerstrs: string[];
  presentModes: string[];
  onSelect: (verstr: string) => void;
}) {
  return (
    <aside
      className="card"
      style={{
        flex: "1 1 280px", maxWidth: 360, position: "sticky", top: 16,
        maxHeight: "calc(100vh - 32px)", overflowY: "auto",
      }}
    >
      <VersionDetails ws={ws} app={app} node={current} canonical={canonical} edges={edges} olderVerstrs={olderVerstrs} onSelect={onSelect} />
      <ConfigSection ws={ws} app={app} verstr={current.verstr} />
      <div style={{ height: 1, background: "var(--line)", margin: "16px 0" }} />
      <h2 className="section-title">Legend</h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {presentModes.map((mode) => (
          <div key={mode} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <ModeDot mode={mode} />
            <span style={{ color: "var(--text-secondary)" }}>
              {mode === "release" ? "release (promoted rc)" : mode}
            </span>
          </div>
        ))}
      </div>
    </aside>
  );
}
