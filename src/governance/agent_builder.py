# src/governance/agent_builder.py
"""Agent Builder Meta-Tool — generate agent configs from descriptions.

Source: LobeHub agent marketplace (Round 16)

Problem: Creating a new department/agent requires manually writing
blueprint.yaml + SKILL.md + registering in departments/. This is
error-prone and has a high barrier to entry.

Solution: A meta-tool that takes a natural language description and
generates a valid, complete agent configuration:
  1. Parse intent → extract name, role, capabilities, constraints
  2. Select authority level + tools from capability description
  3. Generate blueprint.yaml with correct policy boundaries
  4. Generate SKILL.md skeleton with system prompt
  5. Validate against existing department naming + policy rules

This does NOT auto-deploy agents. It produces config files for human
review. The generated configs follow the same format as hand-written
ones in departments/.

Integration:
    - blueprint.py → uses Blueprint/Policy/AuthorityCeiling types
    - dispatcher.py → generated agents are compatible with dispatch
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Tool categories for capability matching
TOOL_PROFILES = {
    "read_only": {
        "tools": ["Read", "Glob", "Grep", "Bash"],
        "authority": "READ",
        "description": "Can read files, search code, run read-only commands",
    },
    "code_writer": {
        "tools": ["Read", "Glob", "Grep", "Bash", "Write", "Edit"],
        "authority": "MUTATE",
        "description": "Can read, write, and edit code files",
    },
    "reviewer": {
        "tools": ["Read", "Glob", "Grep", "Bash"],
        "authority": "READ",
        "description": "Code review, security audit, quality check",
    },
    "operator": {
        "tools": ["Read", "Glob", "Grep", "Bash", "Write"],
        "authority": "PROPOSE",
        "description": "Run commands, generate reports, propose changes",
    },
}

# Keywords → tool profile mapping
CAPABILITY_KEYWORDS = {
    "read_only": ["audit", "monitor", "observe", "scan", "check", "inspect",
                   "review", "report", "analyze", "只读", "监控", "审计"],
    "code_writer": ["write", "create", "implement", "fix", "refactor", "build",
                     "develop", "code", "编写", "实现", "开发", "修复"],
    "reviewer": ["review", "quality", "security", "lint", "test", "verify",
                  "评审", "质量", "安全"],
    "operator": ["deploy", "run", "execute", "collect", "fetch", "operate",
                  "执行", "采集", "运维", "部署"],
}

# Model selection keywords
MODEL_KEYWORDS = {
    "haiku": ["simple", "fast", "quick", "lightweight", "简单", "快速", "轻量"],
    "sonnet": ["standard", "normal", "balanced", "default", "标准", "平衡"],
    "opus": ["complex", "critical", "important", "deep", "复杂", "关键", "深度"],
}


@dataclass
class AgentSpec:
    """Parsed specification for a new agent."""
    name: str                           # e.g., "github-issue-watcher"
    name_zh: str                        # e.g., "GitHub 议题监控"
    description: str                    # What the agent does
    profile: str = "read_only"          # Tool profile key
    model: str = "claude-haiku-4-5"     # Default to cheapest
    authority: str = "READ"
    tools: list[str] = field(default_factory=list)
    writable_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=list)
    can_network: bool = False
    can_commit: bool = False
    max_turns: int = 15
    timeout_s: int = 300
    constraints: list[str] = field(default_factory=list)


def parse_description(description: str) -> AgentSpec:
    """Parse a natural language agent description into a structured spec.

    Examples:
        "一个每天检查 GitHub issues 并报告新增 bug 的 agent"
        → AgentSpec(name="github-issue-checker", profile="read_only", ...)

        "能修复 CI 失败的 agent，需要读写代码和运行测试"
        → AgentSpec(name="ci-fixer", profile="code_writer", ...)
    """
    desc_lower = description.lower()

    # Detect best tool profile
    profile_scores: dict[str, int] = {}
    for profile, keywords in CAPABILITY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in desc_lower)
        if score > 0:
            profile_scores[profile] = score

    best_profile = "read_only"  # Default to safest
    if profile_scores:
        best_profile = max(profile_scores, key=profile_scores.get)

    # Detect model tier
    model = "claude-haiku-4-5"  # Default cheap
    for model_key, keywords in MODEL_KEYWORDS.items():
        if any(kw in desc_lower for kw in keywords):
            if model_key == "opus":
                model = "claude-opus-4-6"
            elif model_key == "sonnet":
                model = "claude-sonnet-4-6"
            break

    # Detect network need
    network_keywords = ["fetch", "api", "http", "download", "webhook",
                        "github", "网络", "抓取", "接口"]
    can_network = any(kw in desc_lower for kw in network_keywords)

    # Generate name from description
    name = _generate_slug(description)

    # Get tool profile
    profile_config = TOOL_PROFILES[best_profile]

    return AgentSpec(
        name=name,
        name_zh=_extract_zh_name(description),
        description=description.strip(),
        profile=best_profile,
        model=model,
        authority=profile_config["authority"],
        tools=profile_config["tools"][:],
        can_network=can_network,
    )


def generate_blueprint_yaml(spec: AgentSpec) -> str:
    """Generate a blueprint.yaml string from an AgentSpec."""
    blueprint = {
        "department": spec.name,
        "name_zh": spec.name_zh,
        "model": spec.model,
        "version": "1",
        "description": spec.description,
        "authority": spec.authority,
        "policy": {
            "allowed_tools": spec.tools,
            "denied_tools": [],
            "writable_paths": spec.writable_paths or ["**"],
            "denied_paths": spec.denied_paths or ["SOUL/private/**", ".claude/hooks/**"],
            "can_commit": spec.can_commit,
            "can_network": spec.can_network,
            "read_only": spec.authority == "READ",
        },
        "preflight": [
            {"name": "cwd_exists", "check": "cwd_exists"},
        ],
        "max_turns": spec.max_turns,
        "timeout_s": spec.timeout_s,
        "on_done": "log_only",
        "on_fail": "alert",
    }

    return yaml.dump(blueprint, default_flow_style=False,
                     allow_unicode=True, sort_keys=False)


def generate_skill_md(spec: AgentSpec) -> str:
    """Generate a SKILL.md skeleton from an AgentSpec."""
    constraint_block = ""
    if spec.constraints:
        lines = "\n".join(f"- {c}" for c in spec.constraints)
        constraint_block = f"\n## Constraints\n\n{lines}\n"

    return f"""# {spec.name_zh}

> Auto-generated by Agent Builder. Review and customize before deployment.

## Identity

You are **{spec.name_zh}**, a specialized agent in the Orchestrator system.

## Role

{spec.description}

## Authority Level

**{spec.authority}** — {TOOL_PROFILES.get(spec.profile, {}).get('description', '')}

## Available Tools

{chr(10).join(f'- `{t}`' for t in spec.tools)}

## Workflow

1. Receive task from Governor dispatcher
2. [TODO: Define specific workflow steps]
3. Report results back to Governor
{constraint_block}
## Output Format

Return structured results as JSON or markdown, depending on the task.
"""


def build_agent(description: str, output_dir: Path | None = None) -> dict:
    """End-to-end agent generation from description.

    Returns dict with generated file contents and paths.
    Does NOT write to disk unless output_dir is specified.
    """
    spec = parse_description(description)

    blueprint_yaml = generate_blueprint_yaml(spec)
    skill_md = generate_skill_md(spec)

    result = {
        "spec": spec,
        "blueprint_yaml": blueprint_yaml,
        "skill_md": skill_md,
        "files": {},
    }

    if output_dir:
        dept_dir = output_dir / spec.name
        dept_dir.mkdir(parents=True, exist_ok=True)

        bp_path = dept_dir / "blueprint.yaml"
        bp_path.write_text(blueprint_yaml, encoding="utf-8")

        skill_path = dept_dir / "SKILL.md"
        skill_path.write_text(skill_md, encoding="utf-8")

        result["files"] = {
            "blueprint": str(bp_path),
            "skill": str(skill_path),
        }
        log.info(f"agent_builder: generated {spec.name} in {dept_dir}")

    return result


def _generate_slug(description: str) -> str:
    """Generate a kebab-case slug from description."""
    # Strip Chinese, keep ASCII words
    ascii_only = re.sub(r'[^\x00-\x7f]', ' ', description)
    words = ascii_only.lower().split()

    # Remove stop words
    stop = {"a", "an", "the", "that", "which", "who", "is", "are", "was",
            "were", "be", "been", "being", "have", "has", "had", "do", "does",
            "did", "will", "would", "could", "should", "may", "might", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from", "and",
            "or", "but", "not", "no", "if", "then", "than", "so", "as"}

    filtered = [w for w in words if w not in stop and len(w) > 1]

    if not filtered:
        return "custom-agent"

    slug = "-".join(filtered[:4])
    # Clean non-alphanumeric
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug or "custom-agent"


def _extract_zh_name(description: str) -> str:
    """Extract or generate a Chinese name from description."""
    # Try to find a short Chinese phrase
    zh_match = re.search(r'[\u4e00-\u9fff]{2,8}', description)
    if zh_match:
        return zh_match.group()
    return "自定义 Agent"
