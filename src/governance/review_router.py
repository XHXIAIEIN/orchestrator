"""R47 (Archon): Smart PR Review Routing.

Cheap classifier (haiku-level) determines PR type, routes to relevant
review agents only. Skips irrelevant agents to save tokens and reduce noise.

PR types: docs-only, frontend, backend, infra, mixed
Each type maps to a subset of review agents.
"""
import logging
import re
from typing import Sequence

log = logging.getLogger(__name__)

# PR type → which review agents to run
REVIEW_ROUTING = {
    "docs-only": ["reviewer"],
    "frontend": ["reviewer", "sentinel"],
    "backend": ["reviewer", "sentinel", "verifier"],
    "infra": ["reviewer", "sentinel", "operator"],
    "config": ["reviewer"],
    "mixed": ["reviewer", "sentinel", "verifier"],  # full suite
}

# File pattern → PR type (checked in order, first match wins)
_TYPE_PATTERNS = [
    (r"^docs/|\.md$|README", "docs-only"),
    (r"^dashboard/|\.tsx?$|\.css$|\.html$", "frontend"),
    (r"^docker|compose|Dockerfile|\.env|config/|bin/", "infra"),
    (r"^\.claude/|CLAUDE\.md$|\.yaml$|\.json$", "config"),
    (r"\.py$|^src/|^tests/", "backend"),
]


def classify_pr_type(changed_files: Sequence[str]) -> str:
    """Classify a PR based on changed files. Returns PR type string.

    If files span multiple types, returns 'mixed'.
    """
    if not changed_files:
        return "mixed"

    types_seen = set()
    for f in changed_files:
        matched = False
        for pattern, pr_type in _TYPE_PATTERNS:
            if re.search(pattern, f):
                types_seen.add(pr_type)
                matched = True
                break
        if not matched:
            types_seen.add("backend")  # default

    if len(types_seen) == 1:
        return types_seen.pop()
    return "mixed"


def get_review_agents(changed_files: Sequence[str]) -> list[str]:
    """Get the list of review agents to run for a PR.

    Returns agent names based on PR type classification.
    """
    pr_type = classify_pr_type(changed_files)
    agents = REVIEW_ROUTING.get(pr_type, REVIEW_ROUTING["mixed"])
    log.info("review_router: PR type=%s → agents=%s (from %d files)",
             pr_type, agents, len(changed_files))
    return agents


def should_skip_agent(agent_name: str, changed_files: Sequence[str]) -> bool:
    """Check if a specific review agent should be skipped for this PR."""
    needed = get_review_agents(changed_files)
    return agent_name not in needed
