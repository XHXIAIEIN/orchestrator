"""OperationValidator — bidirectional hooks with parameter injection.

Source: R64 Hindsight (hindsight_api/extensions/operation_validator.py)

Current limitation: Shell hooks in .claude/hooks/ can only block/pass.
This module lets the governor MODIFY operation parameters — e.g.,
auto-inject requires_approval=True for high-risk operations.

Design:
  - Pre-operation: validate_X() → ValidationResult (accept/reject/accept_with_params)
  - Post-operation: on_X_complete() → None (audit, notification, state sync)
  - Parameter injection: accept_with() can add/modify params without
    touching the original request
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── Validation result ──

@dataclass(frozen=True)
class ValidationResult:
    """Outcome of a pre-operation validation check.

    ``allowed``         — whether the operation may proceed
    ``reason``          — human-readable explanation (especially for rejections)
    ``injected_params`` — extra params to merge into the operation before execution
    """
    allowed: bool
    reason: str = ""
    injected_params: dict[str, Any] = field(default_factory=dict)

    # ── Factory helpers ──

    @classmethod
    def accept(cls) -> "ValidationResult":
        """Operation is allowed with no modifications."""
        return cls(allowed=True)

    @classmethod
    def reject(cls, reason: str) -> "ValidationResult":
        """Operation is blocked with an explanation."""
        return cls(allowed=False, reason=reason)

    @classmethod
    def accept_with(cls, **params: Any) -> "ValidationResult":
        """Operation is allowed; inject additional parameters."""
        return cls(allowed=True, injected_params=dict(params))


# ── Operation context ──

@dataclass
class OperationContext:
    """Metadata bundle passed to every validator hook."""
    operation_type: str
    agent_id: str
    params: dict
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ── Abstract base ──

class OperationValidator(ABC):
    """Extension point for operation validation and auditing.

    Subclass and implement the abstract pre-hooks.  Override the optional
    post-hooks for auditing or state synchronisation — they default to no-ops
    so partial implementations compile cleanly.

    Pre-hooks fire before the operation and can block or modify it.
    Post-hooks fire after completion; their return value is ignored.
    """

    # ── Pre-hooks (required) ──

    @abstractmethod
    def validate_dispatch(self, ctx: OperationContext) -> ValidationResult:
        """Called before dispatching a sub-agent."""

    @abstractmethod
    def validate_tool_call(self, ctx: OperationContext) -> ValidationResult:
        """Called before executing any tool call."""

    @abstractmethod
    def validate_memory_write(self, ctx: OperationContext) -> ValidationResult:
        """Called before writing to persistent memory."""

    @abstractmethod
    def validate_external_send(self, ctx: OperationContext) -> ValidationResult:
        """Called before sending any external message (Telegram, email, webhook)."""

    # ── Post-hooks (optional no-ops) ──

    def on_dispatch_complete(self, result: dict) -> None:
        """Fired after a dispatch completes (success or failure)."""

    def on_tool_call_complete(self, result: dict) -> None:
        """Fired after a tool call completes."""

    def on_memory_write_complete(self, result: dict) -> None:
        """Fired after a memory write completes."""

    def on_external_send_complete(self, result: dict) -> None:
        """Fired after an external send completes."""

    # ── Tool visibility ──

    def filter_allowed_tools(
        self, tools: frozenset[str], context: dict
    ) -> frozenset[str]:
        """Return the subset of tools visible in the given context.

        Default: all tools are visible.  Override to restrict access per context.
        """
        return tools


# ── Validator chain ──

class ValidatorChain:
    """Runs a sequence of OperationValidators.

    Validation:  first rejection wins.  Injected params from all passing
                 validators are merged (later validators can extend earlier ones).
    Completion:  all post-hooks fire regardless of individual failures.
    """

    # Map operation name → (pre-hook attr, post-hook attr)
    _HOOK_MAP: dict[str, tuple[str, str]] = {
        "dispatch":      ("validate_dispatch",      "on_dispatch_complete"),
        "tool_call":     ("validate_tool_call",      "on_tool_call_complete"),
        "memory_write":  ("validate_memory_write",   "on_memory_write_complete"),
        "external_send": ("validate_external_send",  "on_external_send_complete"),
    }

    def __init__(self, validators: list[OperationValidator]) -> None:
        self._validators = list(validators)

    async def validate(
        self, operation: str, ctx: OperationContext
    ) -> ValidationResult:
        """Run all validators for *operation* in registration order.

        First ``reject`` short-circuits the chain.  Injected params from all
        ``accept_with`` results are accumulated and returned in the final result.
        """
        pre_attr, _ = self._hook_attrs(operation)
        merged_params: dict[str, Any] = {}

        for v in self._validators:
            pre_fn = getattr(v, pre_attr, None)
            if pre_fn is None:
                continue
            try:
                result: ValidationResult = pre_fn(ctx)
            except Exception as exc:
                log.error(
                    "operation_validator: %s.%s raised %s — treating as reject",
                    type(v).__name__, pre_attr, exc,
                )
                return ValidationResult.reject(
                    f"{type(v).__name__} raised an unexpected error: {exc}"
                )

            if not result.allowed:
                return result  # first rejection wins

            merged_params.update(result.injected_params)

        return ValidationResult(allowed=True, injected_params=merged_params)

    async def notify_complete(self, operation: str, result: dict) -> None:
        """Fire post-hooks for *operation* on every validator.

        Individual failures are logged but never propagated.
        """
        _, post_attr = self._hook_attrs(operation)

        for v in self._validators:
            post_fn = getattr(v, post_attr, None)
            if post_fn is None:
                continue
            try:
                post_fn(result)
            except Exception as exc:
                log.warning(
                    "operation_validator: %s.%s raised %s — ignoring",
                    type(v).__name__, post_attr, exc,
                )

    # ── Internals ──

    def _hook_attrs(self, operation: str) -> tuple[str, str]:
        if operation not in self._HOOK_MAP:
            raise ValueError(
                f"Unknown operation: {operation!r}. "
                f"Valid: {sorted(self._HOOK_MAP)}"
            )
        return self._HOOK_MAP[operation]


# ── Concrete implementation: RiskLevelValidator ──

# Operations classified by risk tier
_HIGH_RISK_OPS  = frozenset({"external_send"})
_MEDIUM_RISK_OPS = frozenset({"memory_write"})

# File operation patterns that qualify as destructive
_DESTRUCTIVE_TOOL_PATTERNS = (
    "delete_file", "remove_file", "rm_", "truncate_",
    "overwrite_", "format_disk",
)


class RiskLevelValidator(OperationValidator):
    """Injects governance params based on operation risk level.

    High-risk   → ``requires_approval=True``
    Medium-risk → ``audit_required=True``
    Low-risk    → plain accept, no injection

    Destructive file tool calls are also treated as high-risk.
    """

    def validate_dispatch(self, ctx: OperationContext) -> ValidationResult:
        return ValidationResult.accept()

    def validate_tool_call(self, ctx: OperationContext) -> ValidationResult:
        tool_name: str = ctx.params.get("tool", "")
        is_destructive = any(
            tool_name.startswith(pat) for pat in _DESTRUCTIVE_TOOL_PATTERNS
        )
        if is_destructive:
            log.debug("risk_validator: tool %r flagged as high-risk", tool_name)
            return ValidationResult.accept_with(requires_approval=True)
        return ValidationResult.accept()

    def validate_memory_write(self, ctx: OperationContext) -> ValidationResult:
        return ValidationResult.accept_with(audit_required=True)

    def validate_external_send(self, ctx: OperationContext) -> ValidationResult:
        return ValidationResult.accept_with(requires_approval=True)
