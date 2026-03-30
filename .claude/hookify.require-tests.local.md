---
name: require-tests-before-completion
enabled: true
event: stop
action: warn
---

STOP — Pre-completion checklist. Did you write new code in this session?

If yes, verify BEFORE claiming done:
- Boundary tests (empty input, max values, wrong types) — covered?
- Error paths — tested?
- If no tests written, write them NOW. Do not say "done" without tests.

Root cause: Clawvard execution score stuck at 80/100 across 3 exams — code is functional but consistently lacks edge-case coverage.
