"""Load exec-policy.yaml and evaluate a command against rules.

Usage from bash:
    echo "$COMMAND" | python3 scripts/exec_policy_loader.py
    Exit code 0 = allow, exit code 1 = block (reason on stdout)
"""
import json
import re
import sys
from pathlib import Path

POLICY_PATH = Path(__file__).parent.parent / "config" / "exec-policy.yaml"


def load_rules() -> list[dict]:
    try:
        import yaml
    except ImportError:
        return []
    if not POLICY_PATH.exists():
        return []
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("rules", [])


def _match_pattern(command: str, pattern: str, flags: str = "") -> bool:
    re_flags = re.IGNORECASE if "i" in flags else 0
    return bool(re.search(pattern, command, re_flags))


def evaluate(command: str, rules: list[dict] | None = None) -> tuple[str, str]:
    """Evaluate command against rules. Returns (action, reason)."""
    if rules is None:
        rules = load_rules()

    for rule in rules:
        action = rule.get("action", "allow")
        name = rule.get("name", "unknown")
        description = rule.get("description", "")

        matched = False

        if "match_all" in rule:
            all_match = all(
                _match_pattern(command, p["pattern"], p.get("flags", ""))
                for p in rule["match_all"]
            )
            # Check excludes
            excluded = False
            if all_match and "exclude" in rule:
                excluded = any(
                    _match_pattern(command, p["pattern"], p.get("flags", ""))
                    for p in rule["exclude"]
                )
            matched = all_match and not excluded
        elif "match_any" in rule:
            matched = any(
                _match_pattern(command, p["pattern"], p.get("flags", ""))
                for p in rule["match_any"]
            )

        if matched:
            return action, f"{name}: {description}"

    return "allow", ""


if __name__ == "__main__":
    command = sys.stdin.read().strip()
    if not command:
        sys.exit(0)

    action, reason = evaluate(command)
    if action == "block":
        print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(1)
    else:
        sys.exit(0)
