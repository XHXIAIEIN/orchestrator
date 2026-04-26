"""
review_loop.py — PlanReviewLoop: Non-Progress Detector

Detects doom-loops in fixer/reviewer cycles by tracking pushed-back bullets
per slice across rounds. If any slice has identical non-empty pushed-back bullets
two rounds in a row, the loop is BLOCKED_NON_PROGRESS.
"""

import re

VERDICT_APPROVED = "APPROVED"
VERDICT_CONTINUE = "CONTINUE"
VERDICT_BLOCKED_NON_PROGRESS = "BLOCKED_NON_PROGRESS"
VERDICT_BLOCKED_MAX_ROUNDS = "BLOCKED_MAX_ROUNDS"


class PlanReviewLoop:
    """
    State machine that tracks review round progress.

    Usage:
        loop = PlanReviewLoop(max_rounds=5)
        verdict = loop.advance(fixer_report_text)
        # repeat until verdict != VERDICT_CONTINUE
    """

    def __init__(self, max_rounds: int = 5):
        self.rounds: int = 0
        self.max_rounds: int = max_rounds
        self.prev_pushed_back: dict[str, list[str]] = {}

    def extract_pushed_back(self, fixer_report: str) -> dict[str, list[str]]:
        """
        Parse fixer_report for a '## Pushed Back' section, then extract
        '### <slice-id>' sub-sections.

        If a sub-section contains only '(empty — slice approved this round)'
        → store empty list for that slice.

        Returns: {slice_id: [bullet_text, ...]}
        """
        result: dict[str, list[str]] = {}

        # Find the '## Pushed Back' section body
        pushed_back_match = re.search(
            r'##\s+Pushed Back\s*\n(.*?)(?=\n##\s|\Z)',
            fixer_report,
            re.DOTALL,
        )
        if not pushed_back_match:
            return result

        pushed_back_body = pushed_back_match.group(1)

        # Extract each ### <slice-id> sub-section
        slices = re.findall(
            r'###\s+([^\n]+)\n(.*?)(?=\n###|\n##|\Z)',
            pushed_back_body,
            re.DOTALL,
        )

        for slice_id, body in slices:
            slice_id = slice_id.strip()
            body = body.strip()

            if body == '(empty — slice approved this round)':
                result[slice_id] = []
            else:
                # Collect non-empty bullet lines
                bullets = [
                    line.lstrip('-').strip()
                    for line in body.splitlines()
                    if line.strip().startswith('-') and line.strip() != '-'
                ]
                result[slice_id] = bullets

        return result

    def advance(self, fixer_report: str) -> str:
        """
        Compare current pushed-back bullets against previous round.

        Returns one of the four VERDICT_* constants.
        """
        current = self.extract_pushed_back(fixer_report)

        # Check non-progress: any slice with identical non-empty bullet list
        for slice_id, bullets in current.items():
            if bullets and bullets == self.prev_pushed_back.get(slice_id):
                return VERDICT_BLOCKED_NON_PROGRESS

        # Check max rounds AFTER non-progress so a stuck loop is reported as
        # NON_PROGRESS first (more actionable signal)
        if self.rounds >= self.max_rounds:
            return VERDICT_BLOCKED_MAX_ROUNDS

        # All slices empty → approved
        if all(len(v) == 0 for v in current.values()):
            if current:  # at least one slice must exist
                return VERDICT_APPROVED

        # Progress made — update state and continue
        self.prev_pushed_back = current
        self.rounds += 1
        return VERDICT_CONTINUE


if __name__ == '__main__':
    # ── Inline unit tests ─────────────────────────────────────────────────────

    # Helper: build a fixer report with pushed-back bullets
    def _report(slices: dict[str, list[str]]) -> str:
        lines = ['## Pushed Back', '']
        for sid, bullets in slices.items():
            lines.append(f'### {sid}')
            if bullets:
                for b in bullets:
                    lines.append(f'- {b}')
            else:
                lines.append('(empty — slice approved this round)')
            lines.append('')
        return '\n'.join(lines)

    # ── Test 1: same non-empty pushed-back bullets in two consecutive rounds
    #    → second advance() must return BLOCKED_NON_PROGRESS
    loop1 = PlanReviewLoop()
    report_with_bugs = _report({'slice-1': ['bug A', 'bug B']})
    v1 = loop1.advance(report_with_bugs)
    assert v1 == VERDICT_CONTINUE, f"Test 1a failed: expected CONTINUE, got {v1!r}"
    v2 = loop1.advance(report_with_bugs)
    assert v2 == VERDICT_BLOCKED_NON_PROGRESS, (
        f"Test 1b failed: expected BLOCKED_NON_PROGRESS, got {v2!r}"
    )

    # ── Test 2: all slices empty → APPROVED
    loop2 = PlanReviewLoop()
    all_approved = _report({'slice-1': [], 'slice-2': []})
    v3 = loop2.advance(all_approved)
    assert v3 == VERDICT_APPROVED, f"Test 2 failed: expected APPROVED, got {v3!r}"

    # ── Test 3: max_rounds=2, two CONTINUE rounds → third call returns BLOCKED_MAX_ROUNDS
    loop3 = PlanReviewLoop(max_rounds=2)
    report_progress_a = _report({'slice-1': ['bug A']})
    report_progress_b = _report({'slice-1': ['bug B']})  # different bullets → progress
    report_progress_c = _report({'slice-1': ['bug C']})  # different bullets → progress
    v4 = loop3.advance(report_progress_a)
    assert v4 == VERDICT_CONTINUE, f"Test 3a failed: expected CONTINUE, got {v4!r}"
    v5 = loop3.advance(report_progress_b)
    assert v5 == VERDICT_CONTINUE, f"Test 3b failed: expected CONTINUE, got {v5!r}"
    v6 = loop3.advance(report_progress_c)
    assert v6 == VERDICT_BLOCKED_MAX_ROUNDS, (
        f"Test 3c failed: expected BLOCKED_MAX_ROUNDS, got {v6!r}"
    )

    print("All tests passed.")
