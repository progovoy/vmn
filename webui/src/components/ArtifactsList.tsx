function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ArtifactsList({ artifacts, downloadUrl }: {
  artifacts: { name: string; size: number }[];
  downloadUrl: (filename: string) => string;
}) {
  if (artifacts.length === 0) return null;

  return (
    <div className="card">
      <div className="eyebrow">artifacts</div>
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {artifacts.map((a) => (
          <li
            key={a.name}
            style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "6px 0", borderBottom: "1px solid var(--line)",
            }}
          >
            <a
              href={downloadUrl(a.name)}
              download
              style={{ color: "var(--accent)" }}
            >
              {a.name}
            </a>
            <span style={{ color: "var(--text-3)", fontSize: 12 }}>{fmtSize(a.size)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
