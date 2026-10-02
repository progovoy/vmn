/** API tokens (admin): GET/POST /tokens, DELETE /tokens/{id} (revoke). */
import { get, post, del } from "./http";

export type Role = "viewer" | "editor" | "admin";

export interface TokenRecord {
  id: string;
  name: string;
  roles: Record<string, Role>;
  owner: string;
  created_at: number;
  expires_at: number; // 0: never
  revoked: boolean;
}

export interface CreateTokenBody {
  name: string;
  roles: Record<string, Role>;
  ttl_sec?: number;
}

export const apiTokens = {
  list: () => get<TokenRecord[]>("/tokens"),
  create: (body: CreateTokenBody) =>
    post<{ token: string; record: TokenRecord }>("/tokens", body),
  revoke: (id: string) => del(`/tokens/${encodeURIComponent(id)}`),
};
