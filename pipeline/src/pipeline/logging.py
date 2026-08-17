"""Structured JSON logging for the pipeline.

Log records go to two places at once:

* stdout, so that ``docker compose logs pipeline`` shows them.
* a file under the log directory, which satisfies the "log file" deliverable.

Both sinks receive the same JSON line.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.typing import Processor


def configure_logging(level: str, log_dir: Path, filename: str = "pipeline.log") -> Path:
    """Configure structlog and the standard library logging module.

    Args:
        level: Log level name such as ``INFO`` or ``DEBUG``.
        log_dir: Directory that receives the log file. It is created if absent.
        filename: Name of the log file inside ``log_dir``.

    Returns:
        The full path of the log file that was opened.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / filename

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    # The same formatter also renders records from third-party libraries such as
    # httpx, so every line in both sinks is one JSON object.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )

    handlers: list[logging.Handler] = [
        logging.StreamHandler(stream=sys.stdout),
        logging.FileHandler(log_path, encoding="utf-8"),
    ]
    for handler in handlers:
        handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace any handler installed by an earlier call. A repeat call must not
    # duplicate every line.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return log_path


def get_logger(name: str) -> Any:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
