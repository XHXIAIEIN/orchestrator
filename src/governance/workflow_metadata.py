"""Workflow Metadata Sidecar — structured skill routing metadata.

Stolen from DocMason (R45b-P3). Each skill can have a workflow.json sidecar
declaring entry intents, execution hints (mutability, parallelism), and
handoff protocol. Python-side strict validation via frozen dataclass.

Usage:
    from src.governance.workflow_metadata import load_workflow, WorkflowMetadata

    wf = load_workflow(Path(".claude/skills/doctor"))
    if wf and wf.execution_hints.get("parallelism") == "read-only-safe":
        # Safe to run in parallel with other read-only skills
        ...
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Valid values for structured fields
VALID_CATEGORIES = frozenset({
    "diagnostics",   # system health, doctor
    "analysis",      # data analysis, profiling
    "execution",     # run/stop/collect operations
    "review",        # code review, verification
    "learning",      # steal, study external repos
    "communication", # chat, bot interaction
    "automation",    # scheduled tasks, CI
    "meta",          # persona, exam, self-assessment
})

VALID_MUTABILITY = frozenset({"read-only", "workspace-write", "system-write"})
VALID_PARALLELISM = frozenset({"none", "read-only-safe", "per-source-safe"})


@dataclass(frozen=True)
class WorkflowMetadata:
    """Validated, immutable skill workflow metadata."""

    workflow_id: str
    category: str
    entry_intents: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    defaults: dict[str, Any]
    execution_hints: dict[str, Any]
    handoff: dict[str, Any]
    schema_version: int = 1

    @property
    def mutability(self) -> str:
        return self.execution_hints.get("mutability", "workspace-write")

    @property
    def parallelism(self) -> str:
        return self.execution_hints.get("parallelism", "none")

    @property
    def must_return_to_main(self) -> bool:
        return self.execution_hints.get("must_return_to_main_agent", True)

    @property
    def is_parallel_safe(self) -> bool:
        return self.parallelism in ("read-only-safe", "per-source-safe")

    @property
    def completion_signal(self) -> str:
        return self.handoff.get("completion_signal", "")

    @property
    def follow_up_skills(self) -> list[str]:
        return self.handoff.get("follow_up", [])

    @property
    def artifacts(self) -> list[str]:
        return self.handoff.get("artifacts", [])


class WorkflowValidationError(ValueError):
    """Raised when workflow.json fails validation."""
    pass


def _validate_raw(data: dict, source: str) -> None:
    """Validate raw workflow.json data."""
    required = {"workflow_id", "category", "entry_intents"}
    missing = required - set(data.keys())
    if missing:
        raise WorkflowValidationError(f"{source}: missing required fields: {missing}")

    if data.get("category") and data["category"] not in VALID_CATEGORIES:
        raise WorkflowValidationError(
            f"{source}: invalid category '{data['category']}', "
            f"must be one of {sorted(VALID_CATEGORIES)}"
        )

    hints = data.get("execution_hints", {})
    if hints.get("mutability") and hints["mutability"] not in VALID_MUTABILITY:
        raise WorkflowValidationError(
            f"{source}: invalid mutability '{hints['mutability']}'"
        )
    if hints.get("parallelism") and hints["parallelism"] not in VALID_PARALLELISM:
        raise WorkflowValidationError(
            f"{source}: invalid parallelism '{hints['parallelism']}'"
        )


def load_workflow(skill_dir: Path) -> WorkflowMetadata | None:
    """Load and validate workflow.json from a skill directory.

    Returns None if no workflow.json exists (skill uses text-only routing).
    Raises WorkflowValidationError if the file exists but is invalid.
    """
    wf_path = skill_dir / "workflow.json"
    if not wf_path.exists():
        return None

    try:
        data = json.loads(wf_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise WorkflowValidationError(f"{wf_path}: invalid JSON: {e}") from e

    _validate_raw(data, str(wf_path))

    return WorkflowMetadata(
        workflow_id=data["workflow_id"],
        category=data["category"],
        entry_intents=tuple(data.get("entry_intents", [])),
        required_capabilities=tuple(data.get("required_capabilities", [])),
        defaults=data.get("defaults", {}),
        execution_hints=data.get("execution_hints", {}),
        handoff=data.get("handoff", {}),
        schema_version=data.get("schema_version", 1),
    )


def load_all_workflows(skills_root: Path) -> dict[str, WorkflowMetadata]:
    """Load all workflow.json files from skill directories.

    Returns {workflow_id: WorkflowMetadata} for skills that have sidecars.
    Logs warnings for invalid files but doesn't raise.
    """
    result = {}
    if not skills_root.exists():
        return result

    for skill_dir in skills_root.iterdir():
        if not skill_dir.is_dir():
            continue
        try:
            wf = load_workflow(skill_dir)
            if wf:
                result[wf.workflow_id] = wf
        except WorkflowValidationError as e:
            log.warning(f"Skipping invalid workflow: {e}")

    return result


def get_parallel_safe_skills(skills_root: Path) -> list[str]:
    """Return workflow IDs of skills that can safely run in parallel."""
    workflows = load_all_workflows(skills_root)
    return [wid for wid, wf in workflows.items() if wf.is_parallel_safe]


def match_intent(workflows: dict[str, WorkflowMetadata], intent: str) -> list[WorkflowMetadata]:
    """Find workflows whose entry_intents match a given intent string.

    Simple substring matching — intended for quick lookups, not NLP.
    """
    intent_lower = intent.lower()
    matches = []
    for wf in workflows.values():
        for entry_intent in wf.entry_intents:
            if entry_intent.lower() in intent_lower or intent_lower in entry_intent.lower():
                matches.append(wf)
                break
    return matches
