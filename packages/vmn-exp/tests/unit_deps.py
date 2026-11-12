"""``fake_deps(clock)``: what a test hands ``build_app`` so the server derives
run status and runs its indexes on *clock* (a FakeClock), instead of
the real clock ``real_deps`` gives them (plan 44 G11). Everything else is
what ``create_app`` builds on the real IO."""
from vmn_exp.core.real_io import real_io
from vmn_exp.ui.app_deps import ServerDeps, real_deps
from vmn_exp.ui.store_upkeep import StoreUpkeep


def fake_deps(clock, background_refresh=False, keep_warm=None, read_only=False,
              control_plane=None):
    io = real_io()
    deps = real_deps(io, control_plane, background_refresh, read_only, keep_warm)
    upkeep = deps.upkeep and StoreUpkeep(clock=io.clock.monotonic, now=clock.now)
    return ServerDeps(**{**deps.__dict__, "upkeep": upkeep, "status_clock": clock})
