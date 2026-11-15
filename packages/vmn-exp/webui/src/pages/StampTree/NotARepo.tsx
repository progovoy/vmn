export interface NotARepoError {
  reason: "not_a_repo";
  path: string;
  detail: string;
}

export function isNotARepoError(e: unknown): e is Error & { status: number; body: NotARepoError } {
  if (!(e instanceof Error)) return false;
  const ex = e as Error & { status?: number; body?: Record<string, unknown> };
  return ex.status === 409 && ex.body?.reason === "not_a_repo";
}

export function NotARepoMessage({ path }: { path: string }) {
  return (
    <div className="card" style={{ maxWidth: 540 }}>
      <p>
        <strong>Not a git repository</strong> at <code>{path}</code>.
      </p>
      <p style={{ color: "var(--text-muted)", marginTop: 8 }}>
        The workspace path does not contain a valid git repository. Check that the
        directory exists and is a git checkout:
      </p>
      <pre className="cli-card" style={{ marginTop: 8 }}>
        git -C {path} status
      </pre>
    </div>
  );
}
