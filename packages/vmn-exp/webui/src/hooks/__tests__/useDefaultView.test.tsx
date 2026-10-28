/** Plan 28 P4: a page's default team view is applied on first landing,
 *  when the URL carries no view params, and never again in the tab. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { useDefaultView } from "../useDefaultView";
import type { TeamView } from "../../util/teamViews";

const views: TeamView[] = [
  { name: "other", page: "jobs", search: "?sort=x", default: true },
  { name: "health", page: "runs", search: "?show=t%3Ahealth", default: true },
];

function Probe({ views: v, apply, sessionKey = "w/a/runs" }: {
  views: TeamView[] | undefined; apply: (s: string) => void; sessionKey?: string;
}) {
  useDefaultView(sessionKey, v, "runs", apply);
  return null;
}

const mount = (path: string, v: TeamView[] | undefined, apply: (s: string) => void, sessionKey?: string) =>
  render(<MemoryRouter initialEntries={[path]}><Probe views={v} apply={apply} sessionKey={sessionKey} /></MemoryRouter>);

beforeEach(() => sessionStorage.clear());

describe("useDefaultView", () => {
  it("applies the page's default on a bare URL", () => {
    const apply = vi.fn();
    mount("/x?view=all&sel=a", views, apply);
    expect(apply).toHaveBeenCalledTimes(1);
    expect(apply).toHaveBeenCalledWith("?show=t%3Ahealth");
  });

  it("leaves a URL with view params alone", () => {
    const apply = vi.fn();
    mount("/x?sort=loss", views, apply);
    expect(apply).not.toHaveBeenCalled();
  });

  it("waits for the views, then applies once", () => {
    const apply = vi.fn();
    const { rerender } = mount("/x", undefined, apply);
    expect(apply).not.toHaveBeenCalled();
    rerender(<MemoryRouter initialEntries={["/x"]}><Probe views={views} apply={apply} /></MemoryRouter>);
    rerender(<MemoryRouter initialEntries={["/x"]}><Probe views={[...views]} apply={apply} /></MemoryRouter>);
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it("is applied once per tab: a later landing keeps the user's URL", () => {
    const apply = vi.fn();
    mount("/x", views, apply).unmount();
    mount("/x", views, apply);
    expect(apply).toHaveBeenCalledTimes(1);
    mount("/x", views, apply, "w/a/job/r1");
    expect(apply).toHaveBeenCalledTimes(2);
  });

  it("does nothing without a default for the page", () => {
    const apply = vi.fn();
    mount("/x", [{ ...views[1], default: false }], apply);
    mount("/x", [], apply, "k2");
    expect(apply).not.toHaveBeenCalled();
  });
});
