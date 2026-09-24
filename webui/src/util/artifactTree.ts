export interface Artifact {
  name: string;
  size: number;
}

export type ArtifactNode =
  | { kind: "dir"; label: string; path: string; children: ArtifactNode[] }
  | { kind: "file"; label: string; artifact: Artifact };

type Dir = Extract<ArtifactNode, { kind: "dir" }>;

const byKindThenLabel = (a: ArtifactNode, b: ArtifactNode) =>
  a.kind !== b.kind ? (a.kind === "dir" ? -1 : 1) : a.label.localeCompare(b.label);

function sortTree(nodes: ArtifactNode[]): ArtifactNode[] {
  nodes.sort(byKindThenLabel);
  nodes.forEach((n) => { if (n.kind === "dir") sortTree(n.children); });
  return nodes;
}

/** Artifacts nested by their `/`-separated names: folders first, then files. */
export function buildArtifactTree(artifacts: readonly Artifact[]): ArtifactNode[] {
  const root: Dir = { kind: "dir", label: "", path: "", children: [] };
  for (const a of artifacts) {
    const parts = a.name.split("/").filter(Boolean);
    let dir = root;
    parts.slice(0, -1).forEach((part) => {
      const path = dir.path ? `${dir.path}/${part}` : part;
      let next = dir.children.find((n): n is Dir => n.kind === "dir" && n.label === part);
      if (!next) {
        next = { kind: "dir", label: part, path, children: [] };
        dir.children.push(next);
      }
      dir = next;
    });
    dir.children.push({ kind: "file", label: parts[parts.length - 1] ?? a.name, artifact: a });
  }
  return sortTree(root.children);
}
