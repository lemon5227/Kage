"""Configuration loader compatibility module.

Delegates to `core.config.get_config` to maintain compatibility with legacy imports.
"""

from core.config import get_config

__all__ = ["get_config"]
