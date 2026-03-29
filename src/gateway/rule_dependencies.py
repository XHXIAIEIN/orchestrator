"""Rule Dependencies — stolen from Parlant Relational Resolver.

Rules can declare dependencies on tags. When a tag is deactivated,
all rules depending on it are cascade-deactivated.

Dependency types:
  - requires(tag): Rule only active when tag is active
  - requires_any(tag1, tag2): Rule active when ANY listed tag is active
  - requires_all(tag1, tag2): Rule active when ALL listed tags are active

Usage:
    resolver = RuleDependencyResolver()
    resolver.add_rule("code_fix", tags=["engineering", "bugfix"])
    resolver.add_rule("code_review", tags=["quality"], requires=["code_fix"])
    resolver.deactivate_tag("engineering")
    # code_fix becomes inactive -> code_review also cascade-deactivated
    assert not resolver.is_active("code_fix")
    assert not resolver.is_active("code_review")
"""
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class RuleNode:
    """A rule with its dependency declarations."""
    name: str
    tags: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)      # rule names (all must be active)
    requires_any: list[str] = field(default_factory=list)   # rule names (any must be active)
    enabled: bool = True  # manually enabled/disabled


class RuleDependencyResolver:
    """Resolve rule activation based on tag and rule dependencies."""

    def __init__(self):
        self._rules: dict[str, RuleNode] = {}
        self._active_tags: set[str] = set()
        self._all_tags: set[str] = set()

    def add_rule(self, name: str, tags: list[str] = None,
                 requires: list[str] = None,
                 requires_any: list[str] = None):
        """Register a rule with optional dependencies."""
        node = RuleNode(
            name=name,
            tags=tags or [],
            requires=requires or [],
            requires_any=requires_any or [],
        )
        self._rules[name] = node
        for tag in node.tags:
            self._all_tags.add(tag)
            self._active_tags.add(tag)

    def activate_tag(self, tag: str):
        """Activate a tag."""
        self._active_tags.add(tag)
        log.debug(f"rule_deps: activated tag '{tag}'")

    def deactivate_tag(self, tag: str):
        """Deactivate a tag. Rules depending on it will cascade-deactivate."""
        self._active_tags.discard(tag)
        log.info(f"rule_deps: deactivated tag '{tag}'")

    def enable_rule(self, name: str):
        """Manually enable a rule."""
        if name in self._rules:
            self._rules[name].enabled = True

    def disable_rule(self, name: str):
        """Manually disable a rule."""
        if name in self._rules:
            self._rules[name].enabled = False
            log.info(f"rule_deps: manually disabled rule '{name}'")

    def is_active(self, name: str) -> bool:
        """Check if a rule is active (considering dependencies and tags).

        A rule is active when:
        1. It is manually enabled
        2. At least one of its tags is active (if it has tags)
        3. All rules in `requires` are active (transitive)
        4. At least one rule in `requires_any` is active (if specified)
        """
        return self._is_active(name, visited=set())

    def _is_active(self, name: str, visited: set) -> bool:
        """Recursive check with cycle detection."""
        if name in visited:
            return False  # cycle -> treat as inactive
        visited.add(name)

        node = self._rules.get(name)
        if node is None:
            return False

        # Manual disable
        if not node.enabled:
            return False

        # Tag check: if rule has tags, at least one must be active
        if node.tags:
            if not any(tag in self._active_tags for tag in node.tags):
                return False

        # requires: ALL must be active
        for dep in node.requires:
            if not self._is_active(dep, visited.copy()):
                return False

        # requires_any: at least ONE must be active
        if node.requires_any:
            if not any(self._is_active(dep, visited.copy()) for dep in node.requires_any):
                return False

        return True

    def get_active_rules(self) -> list[str]:
        """Return names of all currently active rules."""
        return [name for name in self._rules if self.is_active(name)]

    def get_inactive_rules(self) -> list[str]:
        """Return names of all currently inactive rules."""
        return [name for name in self._rules if not self.is_active(name)]

    def get_cascade_impact(self, tag: str) -> list[str]:
        """Preview which rules would deactivate if a tag is deactivated."""
        was_active = tag in self._active_tags
        self._active_tags.discard(tag)
        inactive = self.get_inactive_rules()
        if was_active:
            self._active_tags.add(tag)
        return inactive

    def get_stats(self) -> dict:
        active = self.get_active_rules()
        return {
            "total_rules": len(self._rules),
            "active_rules": len(active),
            "inactive_rules": len(self._rules) - len(active),
            "active_tags": list(self._active_tags),
            "all_tags": list(self._all_tags),
        }
