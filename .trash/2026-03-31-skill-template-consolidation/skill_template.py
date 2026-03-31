"""Autonomous Skill Templates — stolen from Hermes #492.

A skill template bundles everything needed to deploy a capability:
  - Skill definition (what it does)
  - Tool allowlist (what tools it can use)
  - Preconditions (what must be true before running)
  - Schedule (optional cron expression)
  - Agent config (model, max_turns, timeout)

This is the missing abstraction between "department manifest" (identity + routing)
and "SKILL.md" (free-form instructions). Templates make skills self-contained
and deployable.

Format (YAML):
    name: daily-security-scan
    description: "Scan codebase for security vulnerabilities"
    department: security
    intent: security_scan
    tools: [Bash, Read, Grep, Glob]
    preconditions:
      - type: file_exists
        path: "src/"
      - type: env_var
        name: "ANTHROPIC_API_KEY"
    schedule: "0 6 * * *"  # 6am daily
    agent:
      model: claude-sonnet-4-6
      max_turns: 15
      timeout_s: 300
    on_success: notify_telegram
    on_failure: log_and_retry
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class Precondition:
    """A check that must pass before the skill can run."""
    type: str            # "file_exists", "env_var", "command", "redis_available"
    path: str = ""       # for file_exists
    name: str = ""       # for env_var
    command: str = ""    # for command type
    required: bool = True


@dataclass
class AgentConfig:
    """Agent execution parameters."""
    model: str = "claude-sonnet-4-6"
    max_turns: int = 25
    timeout_s: int = 300
    max_output_tokens: int = 4096


@dataclass
class SkillTemplate:
    """A self-contained, deployable skill unit."""
    name: str
    description: str
    department: str
    intent: str
    tools: list[str] = field(default_factory=list)
    preconditions: list[Precondition] = field(default_factory=list)
    schedule: str = ""           # cron expression, empty = manual only
    agent: AgentConfig = field(default_factory=AgentConfig)
    on_success: str = ""         # action on success
    on_failure: str = "log_only" # action on failure
    enabled: bool = True
    skill_path: str = ""         # path to SKILL.md if exists
    tags: list[str] = field(default_factory=list)

    def check_preconditions(self) -> list[tuple[bool, str]]:
        """Run all preconditions. Returns list of (passed, message)."""
        results = []
        for pre in self.preconditions:
            passed, msg = _check_one(pre)
            results.append((passed, msg))
        return results

    def all_preconditions_met(self) -> bool:
        """Check if all required preconditions pass."""
        for pre in self.preconditions:
            if not pre.required:
                continue
            passed, _ = _check_one(pre)
            if not passed:
                return False
        return True

    def to_task_spec(self, extra_context: str = "") -> dict:
        """Convert to Governor task spec format."""
        return {
            "department": self.department,
            "intent": self.intent,
            "cognitive_mode": "react",
            "priority": "medium",
            "problem": self.description,
            "expected": f"Complete skill: {self.name}",
            "summary": f"[Skill: {self.name}] {self.description}",
            "source": f"skill_template:{self.name}",
            "observation": extra_context or self.description,
            "importance": "Scheduled skill execution",
            "allowed_tools": self.tools,
            "max_turns": self.agent.max_turns,
            "timeout_s": self.agent.timeout_s,
            "model": self.agent.model,
        }


def _check_one(pre: Precondition) -> tuple[bool, str]:
    """Check a single precondition."""
    import os

    if pre.type == "file_exists":
        exists = Path(pre.path).exists()
        return exists, f"file {pre.path}: {'exists' if exists else 'missing'}"

    elif pre.type == "env_var":
        value = os.environ.get(pre.name)
        exists = value is not None and value != ""
        return exists, f"env {pre.name}: {'set' if exists else 'not set'}"

    elif pre.type == "command":
        import subprocess
        try:
            result = subprocess.run(
                pre.command, shell=True, capture_output=True, timeout=10,
            )
            passed = result.returncode == 0
            return passed, f"command '{pre.command}': exit {result.returncode}"
        except Exception as e:
            return False, f"command '{pre.command}': {e}"

    elif pre.type == "redis_available":
        try:
            from src.storage.redis_cache import get_redis
            r = get_redis()
            return r.available, f"redis: {'available' if r.available else 'unavailable'}"
        except Exception:
            return False, "redis: import failed"

    return False, f"unknown precondition type: {pre.type}"


class SkillRegistry:
    """Discover and manage skill templates."""

    def __init__(self, skills_dir: str = "skills"):
        self._skills: dict[str, SkillTemplate] = {}
        self._skills_dir = Path(skills_dir)

    def register(self, skill: SkillTemplate):
        """Register a skill template."""
        self._skills[skill.name] = skill
        log.info(f"skill_registry: registered '{skill.name}' ({skill.department}/{skill.intent})")

    def get(self, name: str) -> Optional[SkillTemplate]:
        return self._skills.get(name)

    def list_all(self) -> list[SkillTemplate]:
        return list(self._skills.values())

    def list_scheduled(self) -> list[SkillTemplate]:
        """Return skills that have a cron schedule."""
        return [s for s in self._skills.values() if s.schedule and s.enabled]

    def list_by_department(self, department: str) -> list[SkillTemplate]:
        return [s for s in self._skills.values() if s.department == department]

    def discover(self) -> int:
        """Discover skill templates from YAML files in skills_dir.

        Returns count of skills discovered.
        """
        if not self._skills_dir.exists():
            return 0

        import yaml
        count = 0
        for yaml_file in self._skills_dir.glob("*.yaml"):
            try:
                skill = load_skill_yaml(yaml_file)
                if skill:
                    self.register(skill)
                    count += 1
            except Exception as e:
                log.warning(f"skill_registry: failed to load {yaml_file}: {e}")

        return count

    def get_stats(self) -> dict:
        return {
            "total": len(self._skills),
            "enabled": sum(1 for s in self._skills.values() if s.enabled),
            "scheduled": len(self.list_scheduled()),
            "departments": list(set(s.department for s in self._skills.values())),
        }


def load_skill_yaml(path: Path) -> Optional[SkillTemplate]:
    """Load a SkillTemplate from a YAML file."""
    import yaml

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data or "name" not in data:
        return None

    preconditions = []
    for pre_data in data.get("preconditions", []):
        preconditions.append(Precondition(
            type=pre_data.get("type", ""),
            path=pre_data.get("path", ""),
            name=pre_data.get("name", ""),
            command=pre_data.get("command", ""),
            required=pre_data.get("required", True),
        ))

    agent_data = data.get("agent", {})
    agent = AgentConfig(
        model=agent_data.get("model", "claude-sonnet-4-6"),
        max_turns=agent_data.get("max_turns", 25),
        timeout_s=agent_data.get("timeout_s", 300),
        max_output_tokens=agent_data.get("max_output_tokens", 4096),
    )

    return SkillTemplate(
        name=data["name"],
        description=data.get("description", ""),
        department=data.get("department", "engineering"),
        intent=data.get("intent", ""),
        tools=data.get("tools", []),
        preconditions=preconditions,
        schedule=data.get("schedule", ""),
        agent=agent,
        on_success=data.get("on_success", ""),
        on_failure=data.get("on_failure", "log_only"),
        enabled=data.get("enabled", True),
        skill_path=data.get("skill_path", ""),
        tags=data.get("tags", []),
    )
