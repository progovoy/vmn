import { describe, it, expect } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { useUrlState } from "../useUrlState";

function setup(initial = "/p?a=1") {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>
  );
  return renderHook(() => ({ state: useUrlState(), loc: useLocation() }), { wrapper });
}

describe("useUrlState", () => {
  it("merges updates into the existing params", () => {
    const { result } = setup("/p?a=1&keep=yes");
    act(() => result.current.state.update((p) => p.set("b", "2")));
    const sp = new URLSearchParams(result.current.loc.search);
    expect(sp.get("a")).toBe("1");
    expect(sp.get("keep")).toBe("yes");
    expect(sp.get("b")).toBe("2");
  });

  it("never loses one of two updates made in the same tick", () => {
    const { result } = setup();
    act(() => {
      result.current.state.update((p) => p.set("x", "1"));
      result.current.state.update((p) => p.set("y", "2"));
    });
    const sp = new URLSearchParams(result.current.loc.search);
    expect(sp.get("x")).toBe("1");
    expect(sp.get("y")).toBe("2");
  });

  it("does not navigate when an update changes nothing", () => {
    const { result } = setup("/p?a=1");
    const before = result.current.loc.key;
    act(() => result.current.state.update((p) => p.set("a", "1")));
    expect(result.current.loc.key).toBe(before);
  });

  it("setParam deletes a param set to an empty value", () => {
    const { result } = setup("/p?a=1&b=2");
    act(() => result.current.state.setParam("a", ""));
    expect(result.current.loc.search).toBe("?b=2");
  });
});
