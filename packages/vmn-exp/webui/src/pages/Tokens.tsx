import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiTokens, type Role, type TokenRecord } from "../apiTokens";
import { PageHead, Skeleton } from "../components/ui";

const ROLES: Role[] = ["viewer", "editor", "admin"];
const KEY = ["tokens"];

const when = (sec: number) => (sec ? new Date(sec * 1000).toLocaleString() : "never");

function roleList(roles: Record<string, Role>) {
  return Object.entries(roles).map(([ws, role]) => `${ws}: ${role}`).join(", ");
}

function CreateForm({ onCreated }: { onCreated: (token: string) => void }) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [ws, setWs] = useState("*");
  const [role, setRole] = useState<Role>("viewer");
  const create = useMutation({
    mutationFn: () => apiTokens.create({ name, roles: { [ws]: role } }),
    onSuccess: (res) => {
      onCreated(res.token);
      setName("");
      client.invalidateQueries({ queryKey: KEY });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <form className="card" onSubmit={submit} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
      <input aria-label="Token name" placeholder="name" value={name} required
        onChange={(e) => setName(e.target.value)} />
      <input aria-label="Workspace" placeholder="workspace or *" value={ws}
        onChange={(e) => setWs(e.target.value)} />
      <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
      </select>
      <button type="submit" disabled={!name || create.isPending}>Create token</button>
      {create.error && <span className="error">{String(create.error)}</span>}
    </form>
  );
}

function TokenRow({ token }: { token: TokenRecord }) {
  const client = useQueryClient();
  const revoke = useMutation({
    mutationFn: () => apiTokens.revoke(token.id),
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  });
  return (
    <tr>
      <td>{token.name}</td>
      <td className="mono">{roleList(token.roles)}</td>
      <td>{token.owner}</td>
      <td>{when(token.expires_at)}</td>
      <td>
        {token.revoked ? <span className="badge">revoked</span> : (
          <button aria-label={`Revoke ${token.name}`} disabled={revoke.isPending}
            onClick={() => revoke.mutate()}>Revoke</button>
        )}
      </td>
    </tr>
  );
}

function TokenTable({ tokens }: { tokens: TokenRecord[] }) {
  if (tokens.length === 0) {
    return <div className="card"><div className="empty" style={{ padding: 16 }}>No API tokens.</div></div>;
  }
  return (
    <div className="card" style={{ padding: 0, overflow: "auto" }}>
      <table style={{ width: "100%" }}>
        <thead>
          <tr><th>name</th><th>roles</th><th>owner</th><th>expires</th><th /></tr>
        </thead>
        <tbody>{tokens.map((t) => <TokenRow key={t.id} token={t} />)}</tbody>
      </table>
    </div>
  );
}

export default function Tokens() {
  const query = useQuery({ queryKey: KEY, queryFn: apiTokens.list });
  const [created, setCreated] = useState<string | null>(null);
  return (
    <>
      <PageHead title="API tokens" what="for scripts calling this server" mono={false} />
      <CreateForm onCreated={setCreated} />
      {created && (
        <div className="card" style={{ marginBottom: 12 }}>
          Copy it now, it is not shown again: <code>{created}</code>
        </div>
      )}
      {query.error && !query.data ? (
        <div className="error">{String(query.error)}</div>
      ) : query.data ? <TokenTable tokens={query.data} /> : <Skeleton />}
    </>
  );
}
