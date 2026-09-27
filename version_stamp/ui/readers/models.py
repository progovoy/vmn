"""Read-side access to the model registry for the vmn ui API.

Uses :mod:`vmn_exp.registry.view` and :mod:`vmn_exp.registry.store` over a
duck-typed experiment storage (the same one experiment routes use).  The
registry lives in the reserved ``vmn-registry`` pseudo-app.
"""
from vmn_exp.registry.store import list_models
from vmn_exp.registry.view import list_model_rows, model_state


def list_models_response(storage) -> dict:
    """Return ``{"models": [ModelRow ...]}`` for the list endpoint."""
    return {"models": list_model_rows(storage)}


def model_detail_response(storage, model_name: str) -> tuple[dict | None, str | None]:
    """Return ``(detail_dict, None)`` or ``(None, error_message)``."""
    detail = model_state(storage, model_name)
    if detail is None:
        return None, f"Model '{model_name}' not found"
    return detail, None
