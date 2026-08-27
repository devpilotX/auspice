"""Structured logging.

Every log line is a structured event. Two reasons that matters more here than in a
typical service. First, the pipeline runs unattended over tens of thousands of documents
and the only way to answer "why did this jurisdiction stop producing facts" is to query
the log by jurisdiction and stage. Second, the data quality metrics in section 16.2 are
computed from these events, so they have to be machine readable rather than prose.

In development the renderer is a console formatter. Anywhere else it is JSON.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.typing import EventDict, Processor

from auspice.config import Environment, get_settings

_configured = False


def _add_stage(_logger: Any, _name: str, event_dict: EventDict) -> EventDict:
    """Promote the pipeline stage to a top level field if a bound logger carries one."""
    stage = event_dict.pop("_stage", None)
    if stage is not None:
        event_dict["stage"] = stage
    return event_dict


def configure_logging(*, level: int | str | None = None, force: bool = False) -> None:
    # Configure once per process. A module level flag is the standard idiom for this and the
    # alternative, a class with a singleton, buys nothing here.
    global _configured  # noqa: PLW0603
    if _configured and not force:
        return

    settings = get_settings()
    resolved_level = (
        level
        if level is not None
        else (logging.DEBUG if settings.env is Environment.development else logging.INFO)
    )

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _add_stage,
    ]

    renderer: Processor
    if settings.env is Environment.development:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    else:
        shared.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(resolved_level)
            if isinstance(resolved_level, str)
            else resolved_level
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Quiet the libraries that log at INFO by default and say nothing useful.
    for noisy in ("httpx", "httpcore", "urllib3", "botocore", "boto3", "s3transfer", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str, **initial: object) -> structlog.stdlib.BoundLogger:
    """A bound logger.

    The module name is bound explicitly rather than through ``add_logger_name``, because the
    print factory has no logger name to read and the stdlib factory would mean routing every
    line through ``logging`` for no gain. Pass the pipeline stage as ``_stage`` and it lands
    as a top level ``stage`` field, which is what the data quality queries group by.
    """
    configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger().bind(logger=name, **initial)
    return logger
