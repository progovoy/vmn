/** Shown above the page when a mutation got a 401: the page stays mounted,
 *  so whatever was typed survives the sign-in. Not a modal on purpose. */
import { useEffect, useId, useRef } from "react";
import { SignInForm } from "./SignIn";
import "./auth.css";

export default function SessionBanner() {
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);

  return (
    <section className="session-banner" role="region" aria-labelledby={headingId}>
      <h2 id={headingId} ref={heading} tabIndex={-1} className="session-banner-title">
        Session ended
      </h2>
      <p className="signin-body">
        Sign in again to continue. Nothing on this page was lost. The action you tried was not
        sent; retry it after signing in.
      </p>
      <SignInForm />
    </section>
  );
}
