"""Retry with exponential backoff for transient lake and IO failures."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from acn_interop.platform.log import get_logger

T = TypeVar("T")
logger = get_logger("retry")


def with_retry(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    base_seconds: float = 0.05,
    exceptions: tuple[type[BaseException], ...] = (OSError, TimeoutError),
) -> T:
    """Run `operation`, backing off until it succeeds or attempts are exhausted."""
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except exceptions as exc:
            last = exc
            if attempt == attempts:
                logger.error("operation failed after %s attempts: %s", attempts, exc)
                raise
            delay = base_seconds * (2 ** (attempt - 1))
            logger.warning(
                "attempt %s/%s failed (%s); sleeping %.2fs",
                attempt,
                attempts,
                exc,
                delay,
            )
            time.sleep(delay)
    assert last is not None
    raise last
