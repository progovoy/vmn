import { describe, it, expect, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useControllable } from "../useControllable";

describe("useControllable", () => {
  it("keeps its own state when uncontrolled", () => {
    const onChange = vi.fn();
    const { result } = renderHook(() => useControllable<number>(undefined, 1, onChange));
    expect(result.current[0]).toBe(1);
    act(() => result.current[1](5));
    expect(result.current[0]).toBe(5);
    expect(onChange).toHaveBeenCalledWith(5);
  });

  it("follows the value prop when controlled", () => {
    const onChange = vi.fn();
    const { result, rerender } = renderHook(({ v }) => useControllable<number>(v, 1, onChange), {
      initialProps: { v: 3 },
    });
    act(() => result.current[1](5));
    expect(result.current[0]).toBe(3);
    expect(onChange).toHaveBeenCalledWith(5);
    rerender({ v: 7 });
    expect(result.current[0]).toBe(7);
  });
});
