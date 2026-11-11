/** A link to the bare page (a nav link, a push) applies the page's default
 *  team view every time, not only on the tab's first landing; what the user
 *  did on the page (an in-place replace to a bare URL: cleared filters, no
 *  view) and Back still keep their URL. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate, type NavigateFunction } from "react-router-dom";
import { useDefaultView } from "../useDefaultView";
import type { TeamView } from "../../util/teamViews";

const views: TeamView[] = [{ name: "health", page: "runs", search: "?show=t%3Ahealth", default: true }];

let navigate: NavigateFunction = () => {};
function Nav() {
  navigate = useNavigate();
  return null;
}

function Probe({ apply }: { apply: (s: string) => void }) {
  useDefaultView("w/a/runs", views, "runs", apply);
  return null;
}

const mount = (apply: (s: string) => void, path = "/x") =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Nav />
      <Routes>
        <Route path="/x" element={<Probe apply={apply} />} />
        <Route path="/y" element={null} />
      </Routes>
    </MemoryRouter>,
  );

const go = (to: string, opts?: { replace?: boolean }) => act(() => { navigate(to, opts); });
const back = () => act(() => { navigate(-1); });

beforeEach(() => sessionStorage.clear());

describe("useDefaultView on a link to the bare page", () => {
  it("applies again after the first landing, the page left and linked back to", () => {
    const apply = vi.fn();
    mount(apply);
    expect(apply).toHaveBeenCalledTimes(1);
    go("/y");
    go("/x");
    expect(apply).toHaveBeenCalledTimes(2);
  });

  it("applies on a link from the page itself with its filters set", () => {
    const apply = vi.fn();
    mount(apply, "/x?sort=loss");
    expect(apply).not.toHaveBeenCalled();
    go("/x");
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it("keeps a bare URL the user replaced in place, and Back", () => {
    const apply = vi.fn();
    mount(apply, "/x?sort=loss");
    go("/x", { replace: true });
    go("/x?sort=acc");
    back();
    expect(apply).not.toHaveBeenCalled();
  });

  it("leaves a link carrying view params alone", () => {
    const apply = vi.fn();
    mount(apply, "/x?sort=loss");
    go("/x?sort=acc");
    expect(apply).not.toHaveBeenCalled();
  });
});
