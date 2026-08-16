"""Structured JSON logging with run correlation (spec 06 §3).

Two processes handle one run: the API accepts it, the worker executes it.
Without a shared correlation id, answering "what happened to run X?" means
reading two log streams and matching on timestamps — which is exactly the
question you ask when something has gone wrong and timestamps are least
trustworthy.

`run_id` travels in a `ContextVar`, so it survives across `await` boundaries
within a task and is never shared between concurrently running jobs. A module
global would leak one run's id into another's log lines under the worker's
default concurrency of four.

JSON because these lines are meant to be queried. Human-readable output stays
available via `LOG_FORMAT=text` for anyone tailing a container by eye.
"""

import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

# Set by whichever layer knows the run: the arq job, or the API handler that
# creates one. Absent outside a run, which is a fact worth logging as null
# rather than papering over with a placeholder.
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_org_id: ContextVar[str | None] = ContextVar("org_id", default=None)

# Attributes LogRecord always carries. Anything else a caller attached via
# `extra=` is application data and gets merged into the line.
_STANDARD = frozenset(
    """args asctime created exc_info exc_text filename funcName levelname levelno lineno
    module msecs message msg name pathname process processName relativeCreated stack_info
    thread threadName taskName""".split()
)


def bind_run(run_id: str | None, org_id: str | None = None) -> None:
    """Bind a run to every subsequent log line in this task.

    No context manager and no reset, because arq runs each job as its own
    asyncio Task and a Task gets a *copy* of the context at creation. Setting
    here therefore cannot leak into a sibling job running concurrently, and the
    binding dies with the task. A module global would leak across all four of
    the worker's concurrent slots.
    """
    _run_id.set(run_id)
    _org_id.set(org_id)


@contextmanager
def run_context(run_id: str | None, org_id: str | None = None):
    """Bind a run for the duration of a block, then restore.

    For callers that continue doing unrelated work afterwards — the API, where
    one process handles many requests.
    """
    run_token = _run_id.set(run_id)
    org_token = _org_id.set(org_id)
    try:
        yield
    finally:
        _run_id.reset(run_token)
        _org_id.reset(org_token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": _run_id.get(),
            "org_id": _org_id.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            # Kept as one string rather than a list: a traceback split across
            # array elements is unreadable in every log viewer.
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Install the formatter on the root handler.

    Replaces existing handlers rather than adding to them: uvicorn and arq both
    install their own, and adding would duplicate every line — the classic
    symptom of a logging setup nobody quite owns.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if fmt == "json"
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())

    # uvicorn's access logger duplicates what its error logger already reports
    # once these are structured; leaving both on doubles the volume for nothing.
    for name in ("uvicorn.access", "uvicorn.error", "arq.worker"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
