/** Lets a page (NotFound, SignIn) retitle the shell it renders inside: the
 *  crumbs and document.title then read that route instead of the URL's. */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type OverrideId = "not-found" | "sign-in";

interface OverrideState {
  override: OverrideId | null;
  setOverride: (id: OverrideId | null) => void;
}

// Without a provider (page tests under a plain MemoryRouter) setting is a no-op.
const OverrideContext = createContext<OverrideState>({ override: null, setOverride: () => {} });

export function ShellOverrideProvider({ children }: { children: ReactNode }) {
  const [override, setOverride] = useState<OverrideId | null>(null);
  return (
    <OverrideContext.Provider value={{ override, setOverride }}>{children}</OverrideContext.Provider>
  );
}

/** Override the shell's route while the calling component is mounted. */
export function useOverrideRoute(id: OverrideId): void {
  const { setOverride } = useContext(OverrideContext);
  useEffect(() => {
    setOverride(id);
    return () => setOverride(null);
  }, [id, setOverride]);
}

export function useShellOverride(): OverrideId | null {
  return useContext(OverrideContext).override;
}
