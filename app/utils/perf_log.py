"""Step timing for diagnosing slow requests (added 2026-11-13 after the infra move).

Lines go straight to stderr (gunicorn -> journald / docker logs) on their own handler,
because Flask's logger drops INFO in production. Find them with:  grep "\\[perf\\]"

Every step logs a "start" line and a "done" line, so a step that hangs shows up as a
start with no matching done. Lines from one request share an id (rid=...), because
gthread workers interleave several requests in the same log.
"""
import logging
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

SLOW_MS = 2000  # "done" lines at or above this are logged as WARNING

_rid: ContextVar[str] = ContextVar("perf_rid", default="-")

perf_log = logging.getLogger("perf")
if not perf_log.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s [perf] %(levelname)s %(message)s"))
    perf_log.addHandler(_handler)
    perf_log.setLevel(logging.INFO)
    perf_log.propagate = False


@contextmanager
def step(name, **ctx):
    """Log start/done (with elapsed ms) around a block. Never swallows exceptions."""
    extra = " ".join(f"{k}={v}" for k, v in ctx.items())
    perf_log.info("rid=%s %s start %s", _rid.get(), name, extra)
    t0 = time.perf_counter()
    outcome = "done"
    try:
        yield
    except BaseException as exc:
        outcome = f"raised {type(exc).__name__}"
        raise
    finally:
        ms = (time.perf_counter() - t0) * 1000
        level = logging.WARNING if ms >= SLOW_MS else logging.INFO
        perf_log.log(level, "rid=%s %s %s %.0fms %s", _rid.get(), name, outcome, ms, extra)


def timed_view(name):
    """Decorator for a view: gives the request an id that nested step() calls inherit.

    Put it directly under @bp.route so the timing includes login/user loading.
    """
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            token = _rid.set(uuid.uuid4().hex[:8])
            try:
                with step(name, **kwargs):
                    return f(*args, **kwargs)
            finally:
                _rid.reset(token)
        return wrapper
    return deco
