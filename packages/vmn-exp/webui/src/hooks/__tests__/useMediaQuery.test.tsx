import { describe, it, expect, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useMediaQuery, NARROW_QUERY, TOUCH_QUERY } from "../useMediaQuery";
import { fakeMedia, dropFakeMedia } from "./fakeMedia";

afterEach(dropFakeMedia);

describe("useMediaQuery", () => {
  it("is false where the browser has no matchMedia (jsdom, old engines)", () => {
    dropFakeMedia();
    expect(renderHook(() => useMediaQuery(NARROW_QUERY)).result.current).toBe(false);
  });

  it("reads the query and follows its changes", () => {
    const media = fakeMedia([NARROW_QUERY]);
    const { result } = renderHook(() => useMediaQuery(NARROW_QUERY));
    expect(result.current).toBe(true);
    act(() => media.set(NARROW_QUERY, false));
    expect(result.current).toBe(false);
  });

  it("names the narrow board (< 640px) and touch-only pointers", () => {
    expect(NARROW_QUERY).toBe("(max-width: 639px)");
    expect(TOUCH_QUERY).toBe("(hover: none) and (pointer: coarse)");
    fakeMedia([TOUCH_QUERY]);
    expect(renderHook(() => useMediaQuery(NARROW_QUERY)).result.current).toBe(false);
    expect(renderHook(() => useMediaQuery(TOUCH_QUERY)).result.current).toBe(true);
  });
});
