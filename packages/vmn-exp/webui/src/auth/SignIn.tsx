/** The sign-in page AuthGate shows on a GET 401, and the form it shares with
 *  the session banner. SSO when the server has OIDC, a pasted token otherwise. */
import { useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api";
import type { HttpError } from "../http";
import { RETURN_TO_KEY } from "../shell/contracts";
import { useOverrideRoute } from "../shell/shellOverride";
import { clearUnauthorized, useAuthState } from "./authState";
import "./auth.css";

function errorText(e: unknown): string {
  const status = (e as HttpError).status;
  if (status === 401) return "That token was not accepted.";
  if (status === undefined) return "Can't reach the server.";
  return (e as Error).message;
}

function TokenForm() {
  const client = useQueryClient();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fieldId = useId();
  const helpId = useId();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    sessionStorage.setItem("vmn_token", token.trim());
    setBusy(true);
    setError(null);
    try {
      await api.meta();
      clearUnauthorized();
      client.invalidateQueries();
    } catch (err) {
      if ((err as HttpError).status === 401) sessionStorage.removeItem("vmn_token");
      setError(errorText(err));
      setBusy(false);
    }
  };

  return (
    <form className="signin-token" onSubmit={submit}>
      <label htmlFor={fieldId}>Token</label>
      <div className="signin-row">
        <input
          id={fieldId} className="mono signin-input" type="password" autoComplete="off"
          aria-describedby={helpId} aria-invalid={error ? true : undefined}
          value={token} onChange={(e) => setToken(e.target.value)}
        />
        <button type="submit" disabled={busy || !token.trim()}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </div>
      <p id={helpId} className="signin-help">
        The --token / VMN_UI_TOKEN value, or a vmnx_… API token.
      </p>
      {error && <p className="signin-error" role="alert">{error}</p>}
    </form>
  );
}

/** The methods the server offers. Without hints (an older server) only the token. */
export function SignInForm() {
  const { hints } = useAuthState();
  const location = useLocation();
  const oidc = !!hints?.oidc && !!hints.login_url;
  const token = !hints || hints.token || !oidc;

  const sso = () => {
    sessionStorage.setItem(RETURN_TO_KEY, location.pathname + location.search);
    window.location.assign(hints!.login_url!);
  };

  return (
    <div className="signin-form">
      {oidc && (
        <button type="button" className="primary signin-sso" onClick={sso}>
          Continue with SSO
        </button>
      )}
      {oidc && token && <p className="signin-or">or paste a token</p>}
      {token && <TokenForm />}
    </div>
  );
}

export default function SignIn() {
  useOverrideRoute("sign-in");
  return (
    <section className="signin">
      <h1 className="signin-title">Sign in to vmn-exp ui</h1>
      <p className="signin-body">This server at {window.location.host} requires sign-in.</p>
      <SignInForm />
    </section>
  );
}
