import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { LegacyCompareRedirect, legacyCompareSearch } from "../legacyRedirects";

const search = (s: string) => new URLSearchParams(s);
const parsed = (s: string) => {
  const p = search(s);
  return { tab: p.get("tab"), sel: p.getAll("sel"), rest: [...p.keys()].filter((k) => k !== "tab" && k !== "sel") };
};

describe("legacyCompareSearch", () => {
  it("maps overlay?runs=a,b to the curves tab", () => {
    expect(parsed(legacyCompareSearch("overlay", search("runs=a,b")))).toEqual({
      tab: "curves", sel: ["a", "b"], rest: [],
    });
  });

  it("maps compare?v=a&to=b to the code tab", () => {
    expect(parsed(legacyCompareSearch("code", search("v=a&to=b")))).toEqual({
      tab: "code", sel: ["a", "b"], rest: [],
    });
  });

  it("keeps a lone side and drops blanks", () => {
    expect(parsed(legacyCompareSearch("code", search("to=b")))).toMatchObject({ sel: ["b"] });
    expect(parsed(legacyCompareSearch("overlay", search("runs=a,,b,")))).toMatchObject({ sel: ["a", "b"] });
  });

  it("encodes refs that need it", () => {
    const out = legacyCompareSearch("code", search("v=%401&to=latest"));
    expect(search(out).getAll("sel")).toEqual(["@1", "latest"]);
  });
});

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
}

const at = (path: string) => render(
  <MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path="/ws/:ws/app/:app/overlay" element={<LegacyCompareRedirect from="overlay" />} />
      <Route path="/ws/:ws/app/:app/compare" element={<LegacyCompareRedirect from="code" />} />
      <Route path="/ws/:ws/app/:app/compare-runs" element={<Where />} />
    </Routes>
  </MemoryRouter>,
);

describe("LegacyCompareRedirect", () => {
  it("sends an old overlay link (a report's, a bookmark's) to the Compare page", async () => {
    at("/ws/w/app/my-app/overlay?runs=a,b");
    expect((await screen.findByTestId("where")).textContent)
      .toBe("/ws/w/app/my-app/compare-runs?tab=curves&sel=a&sel=b");
  });

  it("sends an old code diff link to the code tab", async () => {
    at("/ws/w/app/my-app/compare?v=a&to=b");
    expect((await screen.findByTestId("where")).textContent)
      .toBe("/ws/w/app/my-app/compare-runs?tab=code&sel=a&sel=b");
  });
});
