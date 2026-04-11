"""R48 (Hermes v0.8): Skill Config Interface.

Skills declare required config variables in their SKILL.md frontmatter.
At load time, missing config is detected and reported.

Example frontmatter:
    ---
    name: my-skill
    config:
      API_TOKEN: {required: true, description: "Service API token"}
      MAX_RETRIES: {required: false, default: 3, description: "Retry limit"}
    ---
"""
import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)


def parse_skill_config(frontmatter: dict) -> dict:
    """Extract config declarations from skill frontmatter.

    Returns dict of {var_name: {required, default, description}}.
    """
    config_raw = frontmatter.get("config", {})
    if not isinstance(config_raw, dict):
        return {}

    config = {}
    for var_name, spec in config_raw.items():
        if isinstance(spec, dict):
            config[var_name] = {
                "required": spec.get("required", False),
                "default": spec.get("default"),
                "description": spec.get("description", ""),
            }
        else:
            # Simple value = default
            config[var_name] = {
                "required": False,
                "default": spec,
                "description": "",
            }
    return config


def validate_skill_config(skill_name: str, config_spec: dict) -> dict:
    """Validate that all required config variables are available.

    Checks environment variables and .env file.
    Returns {var_name: resolved_value} for all config vars.
    Missing required vars raise warnings.
    """
    resolved = {}
    missing = []

    for var_name, spec in config_spec.items():
        value = os.environ.get(var_name)
        if value:
            resolved[var_name] = value
        elif spec.get("default") is not None:
            resolved[var_name] = spec["default"]
        elif spec.get("required"):
            missing.append(var_name)
            log.warning("skill_config: skill '%s' requires %s (%s) — not set",
                        skill_name, var_name, spec.get("description", ""))
        # Optional with no default = skip

    if missing:
        log.warning("skill_config: skill '%s' has %d missing required config vars: %s",
                    skill_name, len(missing), ", ".join(missing))

    return resolved


def get_missing_config(skill_name: str, config_spec: dict) -> list[dict]:
    """Get list of missing required config variables (for onboarding prompts)."""
    missing = []
    for var_name, spec in config_spec.items():
        if spec.get("required") and not os.environ.get(var_name):
            if spec.get("default") is None:
                missing.append({
                    "var": var_name,
                    "description": spec.get("description", ""),
                    "skill": skill_name,
                })
    return missing
