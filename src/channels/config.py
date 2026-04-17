"""Shim — channel config moved to orchestrator_channels.config."""
from orchestrator_channels.config import *  # noqa: F401,F403
from orchestrator_channels import config as _module

__all__ = getattr(_module, "__all__",
                  [name for name in dir(_module) if not name.startswith("_")])
