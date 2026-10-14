/** Who a writer identity names, as a row's `author` does: the git email,
 *  else the OS user, else the writer. Servers send identities as objects
 *  (`{git_user_email, os_user, writer}`) or, older records, as a string. */
export type Identity = string | { git_user_email?: string; os_user?: string; writer?: string };

export function identityName(who: Identity | null | undefined): string | null {
  if (typeof who === "string") return who.trim() || null;
  const fields = (who ?? {}) as Record<string, unknown>;
  for (const key of ["git_user_email", "os_user", "writer"]) {
    const value = fields[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}
