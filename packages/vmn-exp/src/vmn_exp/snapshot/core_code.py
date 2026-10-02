"""A vmn-exp runs storage as vmn core's ``code`` store sees it.

Core's code-store helpers (``version_stamp.snapshot.code_store``) address a
code object by the pseudo-app ``vmn-code/<app~>`` and the runs that use it by
the app itself (``vmn snapshot delete`` scans both). Pseudo-app calls go to
the root's ``code`` area under the app key, where
:mod:`vmn_exp.core.code_store` keeps code objects; app calls to the runs.

Public: ``CoreCodeStore(runs storage)``.
"""
from vmn_exp.core.code_store import code_storage

_PSEUDO_APP = "vmn-code/"


class CoreCodeStore:
    def __init__(self, runs):
        self._runs = runs

    def __getattr__(self, name):
        method = getattr(self._runs, name)
        if not callable(method):
            return method

        def call(app_name, *args, **kwargs):
            if not app_name.startswith(_PSEUDO_APP):
                return method(app_name, *args, **kwargs)
            app = app_name[len(_PSEUDO_APP):].replace("~", "/")
            return getattr(code_storage(self._runs), name)(app, *args, **kwargs)

        return call

