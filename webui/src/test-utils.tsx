/** Render helpers for tests: every render gets a fresh client built by the
 *  production factory, so no cache leaks between tests. */
import { render } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { createQueryClient } from "./queryClient";

/** Render `ui` (router wrappers included) under its own QueryClientProvider. */
export function renderWithClient(ui: ReactElement) {
  return render(<QueryClientProvider client={createQueryClient()}>{ui}</QueryClientProvider>);
}
