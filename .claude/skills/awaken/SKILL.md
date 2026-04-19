---
name: awaken
description: "新仓库落地时强制执行发现仪式，禁止模板复制"
origin: "R81 loki-skills-cli steal — forced re-discovery pattern"
source_version: "2026-04-18"
---

# Awaken — New Repo Discovery Ritual

You are landing in an unfamiliar repository. Before writing a single line of code, you must complete this ritual in full. The goal is understanding, not setup — you must be able to explain this repo from memory before touching it.

**BANNED: copying any section verbatim from README, CLAUDE.md, or any template. Write each section from understanding, not from paste.**

## Step 1 — Discovery

Run the following to read project fundamentals:

```bash
cat README.md 2>/dev/null; cat CLAUDE.md 2>/dev/null; ls docs/ 2>/dev/null
```

Gate: Before continuing to Step 2, you must be able to state the project's primary purpose in one sentence — from memory, not from re-reading. If you cannot, re-read and try again until you can.

## Step 2 — Architecture Trace

Spawn one sub-agent with the following literal-path arguments (no variables, no relative paths):

```
SOURCE_DIR="<absolute-path-of-new-repo>"
DEST_DIR="<absolute-path-of-new-repo>/.remember/"
```

Sub-agent task: search for architecture decision records and key design documents:

```bash
grep -r "ADR\|architecture\|AGENTS\|spec" $SOURCE_DIR --include="*.md" -l
```

Sub-agent writes findings to `$DEST_DIR/onboard-trace-MMDD.md` (MMDD = today's date, e.g., `0418`).

## Step 3 — Convention Articulation

Write `.orchestrator-instance.md` in the project root. This file must contain:

- **(a)** Project purpose in your own words — not copy-pasted from README or docs
- **(b)** Three non-obvious conventions found during the architecture trace — things that would surprise a newcomer
- **(c)** Which Orchestrator skills are relevant to this repo and why

Gate: Do not write this file until you can explain each convention from memory without re-reading the source files. Write from understanding.

## Step 4 — Commit

Commit the instance file on a dedicated onboarding branch:

```bash
git checkout -b onboard/<repo-slug>
git add .orchestrator-instance.md
git commit -m "chore(onboard): Orchestrator awakens in <repo-slug>"
```

Replace `<repo-slug>` with the repo directory name (e.g., `my-project`).

## Step 5 — Retrospective

Append a one-paragraph retrospective to `.remember/retrospectives.md` noting what surprised you about this repo's conventions. If `.remember/` does not exist, create it first.

Format:
```
## <repo-slug> — YYYY-MM-DD
<One paragraph. What was unexpected? What did you assume that turned out to be wrong? What convention required the most re-reading to understand?>
```

## Rules

- Never invoke this skill mid-task. Awaken is always the first thing you do in an unfamiliar repo, not an afterthought.
- If the owner says "just start working", complete Steps 1-2 silently in the background before writing any code.
- The BANNED clause above is a hard constraint, not a preference.
