/** Wraps the page outlet: a GET 401 swaps the page for the sign-in page (the
 *  sidebar stays), a mutation 401 adds the session banner above the page. */
import type { ReactNode } from "react";
import { useAuthState } from "./authState";
import SessionBanner from "./SessionBanner";
import SignIn from "./SignIn";

export default function AuthGate({ children }: { children: ReactNode }) {
  const { required, method } = useAuthState();
  if (required && method === "GET") return <SignIn />;
  return (
    <>
      {required && <SessionBanner />}
      {children}
    </>
  );
}
