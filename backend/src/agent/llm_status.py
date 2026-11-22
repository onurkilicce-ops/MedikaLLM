"""In-memory record of the most recent real LLM call outcome.

``/health`` must stay cheap, so it never calls the LLM. Instead it reports
the outcome of the last real chat request handled by this process, which
tells operators whether "ready" has actually been exercised end to end.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_state: dict = {"outcome": None, "at": None, "code": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_success() -> None:
    with _lock:
        _state.update(outcome="succeeded", at=_now(), code=None)


def record_failure(code: str) -> None:
    with _lock:
        _state.update(outcome="failed", at=_now(), code=code)


def snapshot() -> dict:
    with _lock:
        if _state["outcome"] is None:
            return {"last_call": "none_since_start"}
        return {
            "last_call": _state["outcome"],
            "last_call_at": _state["at"],
            "last_error_code": _state["code"],
        }


def reset() -> None:  # used by tests
    with _lock:
        _state.update(outcome=None, at=None, code=None)
