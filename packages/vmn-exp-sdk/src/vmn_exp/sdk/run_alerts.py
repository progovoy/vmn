"""``Run.alert()`` and the run's own ``failed`` alert, mixed into ``Run``.

The alert config is built on first use from the ``experiment:`` conf
``start_run()`` already read (``_exp_conf``); conf.yml is not read again.
"""
from vmn_exp.core.alerts import Alerter, alert_if_failed, load_alert_config, make_alert
from vmn_exp.core.writer import create_log_entry


class RunAlerts:
    """Needs ``self._storage``, ``app_name``, ``id``, ``name``, ``_state``,
    ``_exp_conf`` and ``_append`` from the ``Run`` it is mixed into."""

    _alerter_instance = None
    _exp_conf = None

    def alert(self, title, text="", level="info", wait_sec=None):
        """Record an ``alert`` log entry and send it to the configured sinks.

        Repeats of one *title* within *wait_sec* seconds (default: conf
        ``alerts.wait_sec``, 60) are dropped, neither logged nor sent. Returns
        whether this alert went through. Delivery is off-thread and
        best-effort; ``finish()`` waits briefly for it.
        """
        alert = make_alert(
            "alert", self.app_name, self.id, title, text, level,
            run_name=self.name, status="running", run_state=self._state,
        )
        alerter = self._alerter()
        if not alerter.admit(alert["title"], wait_sec):
            return False
        self._append(create_log_entry("alert", title=alert["title"],
                                      text=alert["text"], level=level))
        if alerter.wants("alert"):
            alerter.send_async(alert)
        return True

    def _alerter(self):
        if self._alerter_instance is None:
            self._alerter_instance = Alerter(load_alert_config(self.app_name, self._exp_conf))
        return self._alerter_instance

    def _finish_alerts(self, timeout):
        """At finish: let queued alerts go out, then alert a failure."""
        alerter = self._alerter()
        alerter.drain(timeout)
        alert_if_failed(self._storage, self.app_name, self.id, self._state,
                        alerter, run_name=self.name)
