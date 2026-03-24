# src/governance/learning/pattern_analyzer.py
"""Structured 5-Pattern Department Analysis — rule-based pre-analysis.

evolution-v2 §5.1 specified 5 concrete pattern types that analyze_department_patterns()
should detect. The LLM-based skill_evolver already asks for these dimensions,
but this module provides the structured, deterministic pre-analysis that feeds
into the LLM analysis and can run independently without LLM.

Pattern types:
  1. repeated_failures — same task type keeps failing
  2. slow_tasks — tasks significantly slower than department average
  3. common_files — files edited in >30% of runs
  4. mode_mismatches — cognitive mode doesn't match task outcome
  5. skill_candidates — successful patterns that recur enough to codify
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent


@dataclass
class PatternFinding:
    """A single pattern finding."""
    pattern_type: str   # repeated_failures | slow_tasks | common_files | mode_mismatches | skill_candidates
    severity: str       # high | medium | low
    description: str
    evidence: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class DepartmentPatterns:
    """Complete structured analysis for a department."""
    department: str
    run_count: int = 0
    success_rate: float = 0.0
    avg_duration_s: float = 0.0
    findings: list[PatternFinding] = field(default_factory=list)

    def format(self) -> str:
        lines = [
            f"## {self.department} Pattern Analysis",
            f"Runs: {self.run_count} | Success: {self.success_rate:.0%} | Avg: {self.avg_duration_s:.0f}s",
        ]
        if not self.findings:
            lines.append("No significant patterns found.")
        for f in self.findings:
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(f.severity, "⚪")
            lines.append(f"\n{icon} [{f.pattern_type}] {f.description}")
            for e in f.evidence[:3]:
                lines.append(f"  - {e}")
            if f.suggestion:
                lines.append(f"  → {f.suggestion}")
        return "\n".join(lines)


def analyze_department_patterns(department: str) -> DepartmentPatterns:
    """Run structured 5-pattern analysis on a department's run-log.

    No LLM needed — pure rule-based analysis.
    """
    result = DepartmentPatterns(department=department)

    runs = _load_runs(department)
    if not runs:
        return result

    result.run_count = len(runs)

    done_runs = [r for r in runs if r.get("status") == "done"]
    failed_runs = [r for r in runs if r.get("status") == "failed"]
    result.success_rate = len(done_runs) / max(len(runs), 1)

    durations = [r.get("duration_s", 0) for r in runs if r.get("duration_s")]
    result.avg_duration_s = sum(durations) / max(len(durations), 1)

    # Pattern 1: Repeated failures
    result.findings.extend(_detect_repeated_failures(failed_runs))

    # Pattern 2: Slow tasks
    result.findings.extend(_detect_slow_tasks(runs, result.avg_duration_s))

    # Pattern 3: Common files
    result.findings.extend(_detect_common_files(runs))

    # Pattern 4: Mode mismatches
    result.findings.extend(_detect_mode_mismatches(runs))

    # Pattern 5: Skill candidates
    result.findings.extend(_detect_skill_candidates(done_runs))

    return result


def _detect_repeated_failures(failed_runs: list[dict]) -> list[PatternFinding]:
    """Same summary/keyword keeps appearing in failed runs."""
    if len(failed_runs) < 2:
        return []

    # Group by first significant word in summary
    keywords = Counter()
    for r in failed_runs:
        summary = r.get("summary", "").lower()
        # Extract key action words
        for word in summary.split():
            if len(word) > 3 and word not in ("task", "failed", "error", "the", "for"):
                keywords[word] += 1

    findings = []
    for word, count in keywords.most_common(3):
        if count >= 2:
            examples = [
                r.get("summary", "")[:80]
                for r in failed_runs
                if word in r.get("summary", "").lower()
            ][:3]
            findings.append(PatternFinding(
                "repeated_failures",
                "high" if count >= 3 else "medium",
                f"Keyword '{word}' appears in {count} failed tasks",
                evidence=examples,
                suggestion=f"Add specific guidance for '{word}' tasks to SKILL.md",
            ))

    return findings


def _detect_slow_tasks(runs: list[dict], avg_duration: float) -> list[PatternFinding]:
    """Tasks significantly slower than average."""
    if not avg_duration or avg_duration < 10:
        return []

    threshold = avg_duration * 2.5  # 2.5x average is suspicious
    slow = [r for r in runs if r.get("duration_s", 0) > threshold]

    if not slow:
        return []

    examples = [
        f"{r.get('summary', '?')[:60]} ({r.get('duration_s', 0)}s, mode={r.get('mode', '?')})"
        for r in slow[:5]
    ]

    return [PatternFinding(
        "slow_tasks",
        "medium",
        f"{len(slow)} tasks took >{threshold:.0f}s (avg={avg_duration:.0f}s)",
        evidence=examples,
        suggestion="Check if these tasks need a different cognitive mode or more specific instructions",
    )]


def _detect_common_files(runs: list[dict]) -> list[PatternFinding]:
    """Files that appear in >30% of runs."""
    file_counter = Counter()
    total_with_files = 0

    for r in runs:
        files = r.get("files_changed", [])
        if files:
            total_with_files += 1
            for f in files:
                file_counter[f] += 1

    if total_with_files < 5:
        return []

    threshold = total_with_files * 0.3
    hot_files = [(f, c) for f, c in file_counter.most_common(10) if c >= threshold]

    if not hot_files:
        return []

    return [PatternFinding(
        "common_files",
        "low",
        f"{len(hot_files)} files appear in >30% of runs",
        evidence=[f"{f} ({c}/{total_with_files} runs)" for f, c in hot_files[:5]],
        suggestion="Add context about these files to SKILL.md or guidelines/",
    )]


def _detect_mode_mismatches(runs: list[dict]) -> list[PatternFinding]:
    """Cognitive mode doesn't match task outcome patterns."""
    findings = []

    # Failed tasks using 'direct' mode that might need 'hypothesis' or 'designer'
    direct_fails = [
        r for r in runs
        if r.get("mode") == "direct" and r.get("status") == "failed"
    ]
    if len(direct_fails) >= 2:
        findings.append(PatternFinding(
            "mode_mismatches",
            "medium",
            f"{len(direct_fails)} 'direct' mode tasks failed — some may need hypothesis/react",
            evidence=[r.get("summary", "")[:80] for r in direct_fails[:3]],
            suggestion="Review if these tasks had diagnostic elements that needed hypothesis mode",
        ))

    # Designer mode on simple tasks (very fast completion = overkill)
    designer_fast = [
        r for r in runs
        if r.get("mode") == "designer" and r.get("duration_s", 999) < 30
           and r.get("status") == "done"
    ]
    if len(designer_fast) >= 2:
        findings.append(PatternFinding(
            "mode_mismatches",
            "low",
            f"{len(designer_fast)} 'designer' mode tasks finished in <30s — likely overkill",
            evidence=[r.get("summary", "")[:80] for r in designer_fast[:3]],
            suggestion="These tasks might be better served by 'direct' or 'react' mode",
        ))

    return findings


def _detect_skill_candidates(done_runs: list[dict]) -> list[PatternFinding]:
    """Successful patterns that recur enough to codify as skills."""
    if len(done_runs) < 5:
        return []

    # Find recurring notes (successful approaches mentioned multiple times)
    note_keywords = Counter()
    for r in done_runs:
        notes = r.get("notes", "").lower()
        if not notes:
            continue
        for word in notes.split():
            if len(word) > 4:
                note_keywords[word] += 1

    recurring = [(w, c) for w, c in note_keywords.most_common(5) if c >= 3]
    if not recurring:
        return []

    examples = []
    for word, count in recurring[:3]:
        matching = [
            r.get("notes", "")[:80]
            for r in done_runs
            if word in r.get("notes", "").lower()
        ][:2]
        examples.extend(matching)

    return [PatternFinding(
        "skill_candidates",
        "low",
        f"{len(recurring)} recurring patterns in successful task notes",
        evidence=examples[:5],
        suggestion="Consider codifying these patterns into learned-skills.md",
    )]


def _load_runs(department: str) -> list[dict]:
    """Load run-log.jsonl for a department."""
    run_log = _REPO_ROOT / "departments" / department / "run-log.jsonl"
    if not run_log.exists():
        return []
    runs = []
    try:
        for line in run_log.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                runs.append(json.loads(line))
    except Exception as e:
        log.warning(f"pattern_analyzer: failed to load {run_log}: {e}")
    return runs


def analyze_all_departments() -> dict[str, DepartmentPatterns]:
    """Analyze all departments. Returns {dept_name: DepartmentPatterns}."""
    dept_root = _REPO_ROOT / "departments"
    results = {}
    for d in sorted(dept_root.iterdir()):
        if d.is_dir() and not d.name.startswith((".", "_", "shared")):
            patterns = analyze_department_patterns(d.name)
            if patterns.run_count > 0:
                results[d.name] = patterns
    return results
