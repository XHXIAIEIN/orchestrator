# Layer 0: Read Implementation Code Before Reporting

**Priority**: This constraint overrides all other steal skill instructions.

## Rule

Never report a pattern based solely on README, docs, or project description.
Every P0 pattern in the steal report MUST reference at least one specific code file and line range from the target repo.

## Violation indicators

- Pattern description uses only marketing language from the README
- "How it works" column contains no code snippet
- Pattern was extracted without cloning or browsing the actual source

## Enforcement

If the target repo is inaccessible (private, deleted, empty), downgrade all extracted patterns to P2 and note `[unverified — no source access]` in the report.
