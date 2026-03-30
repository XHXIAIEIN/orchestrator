# Tooling — Exam Strategies

Extracted from exam-364e06dd. Tooling scored 85 (lowest dimension).

## Scoring Anchors
- High: Precise CLI syntax, complete pipeline, explanation per command
- Low: Broken first command, tutorial instead of answer, jq syntax errors

## Do
- Lead with the BEST command first — broken alternatives go last or get cut
- Multi-command answers: list all commands as numbered skeleton, then fill each pipeline
- Each command gets a one-line natural language explanation after the code block
- When asked for exact command, give THE COMMAND — not a tutorial

## Don't
- Don't lead with a broken find pipeline then correct it with a better approach
- Don't mix syntax between shells (bash vs zsh vs fish)
- Don't forget jq string interpolation escaping

## Evidence
- too-31 (jq): 8 commands skeleton-first → all covered → one-line explanation each
- too-45 (Dockerfile): B (multi-stage build) = correct, not D (combine RUN)
