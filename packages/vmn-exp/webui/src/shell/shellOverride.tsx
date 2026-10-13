/** Lets a page (NotFound, SignIn) retitle the shell it renders inside: the
 *  crumbs and document.title then read that route instead of the URL's. A
 *  dead end (a not-found, a failed render) also keeps the URL out of ⌘K's Recent. */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type OverrideId = "not-found" | "sign-in";

interface OverrideState {
  override: OverrideId | null;
  setOverride: (id: OverrideId | null) => void;
  deadEnd: boolean;
  setDeadEnd: (dead: boolean) => void;
}

// Without a provider (page tests under a plain MemoryRouter) setting is a no-op.
const OverrideContext = createContext<OverrideState>({
  override: null, setOverride: () => {}, deadEnd: false, setDeadEnd: () => {},
});

export function ShellOverrideProvider({ children }: { children: ReactNode }) {
  const [override, setOverride] = useState<OverrideId | null>(null);
  const [deadEnd, setDeadEnd] = useState(false);
  return (
    <OverrideContext.Provider value={{ override, setOverride, deadEnd, setDeadEnd }}>
      {children}
    </OverrideContext.Provider>
  );
}

/** Override the shell's route while the calling component is mounted; `null` leaves it. */
export function useOverrideRoute(id: OverrideId | null): void {
  const { setOverride } = useContext(OverrideContext);
  useEffect(() => {
    if (!id) return;
    setOverride(id);
    return () => setOverride(null);
  }, [id, setOverride]);
}

/** Mark the current URL a dead end while the calling component is mounted. */
export function useDeadEnd(): void {
  const { setDeadEnd } = useContext(OverrideContext);
  useEffect(() => {
    setDeadEnd(true);
    return () => setDeadEnd(false);
  }, [setDeadEnd]);
}

export function useShellOverride(): OverrideId | null {
  return useContext(OverrideContext).override;
}

export function useShellDeadEnd(): boolean {
  return useContext(OverrideContext).deadEnd;
}
