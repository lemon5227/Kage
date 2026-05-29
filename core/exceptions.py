"""
Kage Exceptions — project-level exception hierarchy.

Provides typed exceptions for all Kage subsystems so that:
- Callers can catch specific error types instead of bare Exception
- Errors are logged consistently with context
- The @log_exceptions decorator standardizes error handling
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ============================================================================
# Base exception
# ============================================================================

class KageError(Exception):
    """Base exception for all Kage errors."""


# ============================================================================
# Subsystem exceptions
# ============================================================================

class ModelError(KageError):
    """Error calling or loading a language model."""


class ModelCallError(ModelError):
    """Failed to generate a response from the model."""


class ModelLoadError(ModelError):
    """Failed to load a model file or runtime."""


class ToolExecutionError(KageError):
    """A tool call failed to execute."""


class NetworkError(KageError):
    """Network request failed (timeout, DNS, connection refused, etc.)."""


class ConfigError(KageError):
    """Configuration is missing or invalid."""


class MemoryError(KageError):
    """Memory system operation failed."""


class AudioError(KageError):
    """TTS/ASR/audio pipeline failed."""


class AvatarError(KageError):
    """Live2D/avatar animation failed."""


class ServerError(KageError):
    """General server-side error (fallback)."""


# ============================================================================
# Decorator: log exceptions automatically
# ============================================================================

def log_exceptions(
    level: int = logging.ERROR,
    reraise: bool = True,
    fallback: Any = None,
) -> Callable[[F], F]:
    """Decorator that logs exceptions from a function.

    Args:
        level: Logging level (default: ERROR).
        reraise: Whether to re-raise the exception after logging.
        fallback: Value to return if reraise=False and an exception occurs.

    Usage:
        @log_exceptions()
        def risky(): ...

        @log_exceptions(reraise=False, fallback=None)
        def maybe_fails(): ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except KageError:
                # Already a typed Kage error — log and re-raise
                logger.log(level, "%s failed: %s", func.__name__, args[0] if args else "", exc_info=True)
                raise
            except Exception as exc:
                logger.log(level, "%s failed with unexpected error: %s", func.__name__, exc, exc_info=True)
                if reraise:
                    raise
                return fallback
        return wrapper  # type: ignore[return-value]
    return decorator


def log_exceptions_async(
    level: int = logging.ERROR,
    reraise: bool = True,
    fallback: Any = None,
) -> Callable[[F], F]:
    """Async version of log_exceptions."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except KageError:
                logger.log(level, "%s failed: %s", func.__name__, args[0] if args else "", exc_info=True)
                raise
            except Exception as exc:
                logger.log(level, "%s failed with unexpected error: %s", func.__name__, exc, exc_info=True)
                if reraise:
                    raise
                return fallback
        return wrapper  # type: ignore[return-value]
    return decorator
