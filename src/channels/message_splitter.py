"""Shim — message_splitter moved to orchestrator_channels.message_splitter."""
from orchestrator_channels.message_splitter import *  # noqa: F401,F403
from orchestrator_channels import message_splitter as _module

__all__ = getattr(_module, "__all__",
                  [name for name in dir(_module) if not name.startswith("_")])
