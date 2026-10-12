/** Every child route's errorElement: it renders in the shell's outlet, so the
 *  sidebar and topbar survive a page that failed to load or render. */
import { Link, isRouteErrorResponse, useLocation, useNavigate, useRouteError } from "react-router-dom";
import NotFound, { FocusedHeading } from "./NotFound";
import "./NotFound.css";

/** What a browser says when a lazy chunk of an older build is gone. */
const STALE_CHUNK = /dynamically imported module|Importing a module script failed/;

function messageOf(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (isRouteErrorResponse(error)) return `${error.status} ${error.statusText}`;
  return String(error);
}

export default function RouteError() {
  const error = useRouteError();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  if (isRouteErrorResponse(error) && error.status === 404) {
    return <NotFound kind="route" pathname={pathname} />;
  }
  const message = messageOf(error);
  if (STALE_CHUNK.test(message)) {
    return (
      <section className="not-found">
        <FocusedHeading>The dashboard was updated</FocusedHeading>
        <p>This tab runs an older build. Reload to load the new one.</p>
        <div className="nf-actions">
          <button className="primary" onClick={() => window.location.reload()}>Reload</button>
        </div>
      </section>
    );
  }
  return (
    <section className="not-found">
      <FocusedHeading>This page failed to render</FocusedHeading>
      <pre>{message}</pre>
      <div className="nf-actions">
        <button className="primary" onClick={() => navigate(0)}>Try again</button>
        <Link className="nf-action" to="/">All workspaces</Link>
      </div>
    </section>
  );
}
