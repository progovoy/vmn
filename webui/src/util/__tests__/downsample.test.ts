import { describe, it, expect } from "vitest";
import { downsampleLTTB } from "../downsample";

describe("downsampleLTTB", () => {
  it("passes through when data.length <= maxPoints", () => {
    const data = [{x:0,y:1},{x:1,y:2},{x:2,y:3}];
    expect(downsampleLTTB(data, 5)).toEqual(data);
    expect(downsampleLTTB(data, 3)).toEqual(data);
  });

  it("returns maxPoints items when input is longer", () => {
    const data = Array.from({length: 100}, (_, i) => ({x: i, y: Math.sin(i * 0.1)}));
    const result = downsampleLTTB(data, 20);
    expect(result).toHaveLength(20);
  });

  it("preserves first and last points", () => {
    const data = Array.from({length: 100}, (_, i) => ({x: i, y: i * i}));
    const result = downsampleLTTB(data, 10);
    expect(result[0]).toEqual(data[0]);
    expect(result[result.length - 1]).toEqual(data[data.length - 1]);
  });

  it("handles empty array", () => {
    expect(downsampleLTTB([], 10)).toEqual([]);
  });

  it("handles single point", () => {
    const data = [{x: 0, y: 1}];
    expect(downsampleLTTB(data, 10)).toEqual(data);
  });

  it("handles two points", () => {
    const data = [{x: 0, y: 0}, {x: 1, y: 1}];
    expect(downsampleLTTB(data, 10)).toEqual(data);
  });

  it("handles maxPoints of 2", () => {
    const data = Array.from({length: 50}, (_, i) => ({x: i, y: i}));
    const result = downsampleLTTB(data, 2);
    expect(result).toHaveLength(2);
    expect(result[0]).toEqual(data[0]);
    expect(result[1]).toEqual(data[49]);
  });

  it("output is sorted by x", () => {
    const data = Array.from({length: 200}, (_, i) => ({x: i, y: Math.sin(i * 0.05)}));
    const result = downsampleLTTB(data, 30);
    for (let i = 1; i < result.length; i++) {
      expect(result[i].x).toBeGreaterThan(result[i-1].x);
    }
  });
});
