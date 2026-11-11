"""How a ``Run`` ends — ``finish()``, ``release()``, ``detach()`` and the
context manager — mixed into ``Run``.

Tests patch ``compact_by``, ``error_from_exception`` and
``FINAL_REMOTE_TIMEOUT_SEC`` on ``vmn_exp.sdk.run``, so this module never
imports them: it reaches them through the instance (``_compact_by``,
``_error_from_exception``, ``_final_deadline``, ``_time_left``), methods
``Run`` defines in that module, which look the names up at call time.
"""
import logging

from vmn_exp._base import now_iso
from vmn_exp.core.run_error import error_from_message
from vmn_exp.core.writer import create_log_entry, own_stream
from vmn_exp.sdk import context, release
from vmn_exp.sdk.exit_code import exit_status

# The run module's logger: the close path's warnings keep the logger they had.
_LOGGER = logging.getLogger("vmn_exp.sdk.run")

# How long finish() waits for run.alert() deliveries still in flight.
ALERT_DRAIN_SEC = 5


class RunClose:
    """Needs ``self._storage``, ``app_name``, ``id``, ``_writer``, ``_state``,
    ``_finished``, ``_detached``, ``_gate``, ``_heartbeat``, ``_log_buffer``,
    ``_log_sync``, ``_state_publisher``, ``_output``, ``_media_uploads``,
    ``_record_guard``, ``_in_owner``, ``_append``, ``_publish``,
    ``_duration``, ``_remote_writers``, ``_undefer_ships`` and the four
    call-time lookups above from the ``Run`` it is mixed into."""

    def finish(self, exit_code=0, error=None):
        """Finalize the run. Idempotent: a second call changes nothing.

        False when another attempt of the run (a duplicate pod, a resumed
        one) finished it first: its final state stays, this one is dropped
        with a warning. True otherwise — also when the final upload is still
        in flight at the deadline.

        *error* — an exception or a message — is recorded as the final run
        state's ``error`` (and an ``error`` log entry), whatever *exit_code* is.

        Never raises for a storage failure (a flaky remote at the end of a long
        run is logged, not thrown at the workload), and always closes the run —
        it leaves the open-run registry and hands the env back either way.
        """
        return self._finish(exit_code, error=error)

    def release(self, reason=None):
        """Hand the run back unfinished, for another attempt to reopen with
        ``start_run(run_id=...)``: everything logged so far is flushed and
        synced, recording stops, and the run reads as waiting (``created``)
        with ``end_reason: released`` (*reason* as ``release_reason``).
        Idempotent; a no-op on a finished run. Never raises for a storage
        failure, like :meth:`finish`. False, like :meth:`finish`, when another
        attempt finished the run: the release is dropped, its ending stays."""
        deadline = self._final_deadline()
        if self._record_release(deadline, reason=reason):
            self._close_remote_writers(deadline)
        return not self._state_publisher.superseded

    def detach(self):
        """Walk away from the run without writing anything more to the store —
        no final state, no release, not even a last heartbeat — for an attempt
        that lost the run to another one. Its threads stop (waiting, within the
        final-upload timeout, for a write already in flight), what is still
        queued is dropped and the run leaves this process's context, so
        atexit and SIGTERM leave it alone. Logging afterwards records nothing;
        ``finish()``, ``release()`` and the context manager's exit write
        nothing. Idempotent; a no-op on a finished run."""
        if self._finished or not self._in_owner():
            return
        self._finished = self._detached = True
        try:
            self._stop_background(self._final_deadline())
        finally:
            self._undefer_ships()
            context.unregister(self)

    def _stop_background(self, deadline):
        """Stop a detached run's threads; its closed gate skips their last calls."""
        self._gate.close(self._time_left(deadline))
        self._heartbeat.stop()
        self._log_buffer.discard()
        if self._output is not None:
            self._output.stop()
        self._media_uploads.close(self._time_left(deadline))
        self._close_writers(deadline)

    def _finish(self, exit_code, error=None, **final_state):
        deadline = self._final_deadline()
        if self._record_final(exit_code, deadline, error=error, **final_state):
            self._close_remote_writers(deadline)
        return not self._state_publisher.superseded

    def _record_error(self, error):
        """Append the ``error`` log entry of *error*; return its run-state mapping."""
        if isinstance(error, BaseException):
            recorded = self._error_from_exception(error)
            entry = create_log_entry(
                "error",
                exception=type(error).__name__,
                message=recorded["message"],
                traceback=recorded["traceback"],
            )
        else:
            recorded = error_from_message(error)
            entry = create_log_entry("error", message=recorded["message"])
        self._record_guard("error entry", self._append, entry)
        return recorded

    def _record_final(self, exit_code, deadline, error=None, media_share=1.0, **final_state):
        """Write the run's last log entries and final state locally, queue their
        upload and close the run. False if it was finished already."""

        def outcome():
            duration = self._duration()
            if error is not None:
                recorded = self._record_guard("error", self._record_error, error)
                if recorded is not None:
                    final_state["error"] = recorded
            self._record_guard(
                "run entry",
                self._append,
                create_log_entry(
                    "run",
                    command=self._state["command"],
                    exit_code=exit_code,
                    duration_sec=duration,
                ),
            )
            return dict(state="finished", exit_code=exit_code, finished_at=now_iso(),
                        duration_sec=duration, **final_state)

        return self._close_attempt(deadline, outcome, alerts=True, media_share=media_share)

    def _record_release(self, deadline, reason=None, signal=None, media_share=1.0):
        """:meth:`_record_final` of a released attempt (no exit code, no alerts)."""
        return self._close_attempt(
            deadline, lambda: release.released_state(self._duration(), reason, signal),
            media_share=media_share)

    def _close_attempt(self, deadline, outcome, alerts=False, media_share=1.0):
        """Stop recording, write *outcome()*'s state last, queue the uploads
        and close the run. False if it was closed already.

        Media files are waited for first, for *media_share* of what is left
        until *deadline*: their entries are appended as they are stored, so
        they must land before the final flush.
        """
        if self._finished or not self._in_owner():
            return False
        self._finished = True
        # A paused run still drains: its last uploads must not wait for a resume.
        self._gate.release()

        try:
            # Before the heartbeat stops: a long final upload is not a stuck run.
            self._record_guard(
                "media files",
                self._close_media_uploads,
                self._time_left(deadline) * media_share,
            )
            self._heartbeat.stop(self._time_left(deadline))
            final_state = outcome()
            if self._output is not None:
                self._record_guard("output log", self._record_output)
            # The log lands before the final state: a reader that sees the run
            # finished must also see everything it logged.
            self._record_guard("buffered log", self._log_buffer.close)
            self._record_guard("final state", self._publish, final_state, final=True)
            # A later request would replace the final sync with a periodic one.
            self._undefer_ships()
            self._log_sync.submit(final=True)
            if alerts:
                self._record_guard("alerts", self._finish_alerts, ALERT_DRAIN_SEC)
        except BaseException:
            context.unregister(self)
            raise
        # Still uploading: a fork waits for it until _close_remote_writers ends.
        context.mark_closing(self)
        return True

    def _record_output(self):
        self._append(self._output.stop())

    def _close_remote_writers(self, deadline):
        try:
            # One deadline for all: they upload in parallel, so waiting for each
            # in turn would double the worst case.
            for what, error in self._close_writers(deadline):
                _LOGGER.warning(self._not_uploaded(what, error))
            self._compact_by(self._storage, self.app_name, self.id,
                             own_stream(self._storage, self.app_name, self.id, self._writer),
                             deadline)
        finally:
            context.closed(self)

    def _close_writers(self, deadline):
        """Close the remote writers; ``(name, last error or None)`` of each
        whose final upload did not land."""
        return [(what, getattr(writer, "last_error", None))
                for what, writer in self._remote_writers()
                if not writer.close(self._time_left(deadline))]

    def _not_uploaded(self, what, error):
        if error is None:
            return f"vmn: the final {what} of run {self.id} is still uploading"
        from vmn_exp.storage.cached import SHIP_LATER_HINT, is_log_buffer

        hint = f"; {SHIP_LATER_HINT}" if is_log_buffer(self._storage) else ""
        return f"vmn: the final {what} of run {self.id} was not uploaded: {error}{hint}"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._finished:
            return False
        if exc is None:
            self.finish()
            return False
        if isinstance(exc, SystemExit):
            # sys.exit(0) inside the block is a clean, intentional exit — not
            # an error — and the real code (when non-zero) beats a generic 1.
            self.finish(exit_code=exit_status(exc.code))
            return False
        self.finish(exit_code=1, error=exc)
        return False  # never swallow — nor replace — the workload's exception
