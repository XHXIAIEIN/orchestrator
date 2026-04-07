# Skill Routing Decision Tree

When a task arrives, route through this tree instead of scanning the full skill list.
Stop at the first matching leaf — don't keep searching.

## Stage 1: What kind of work?

```
Task arrives
├─ Bug / error / unexpected behavior?
│  └→ systematic-debugging (then verification-gate when done)
│
├─ Create / build / add new feature?
│  ├─ Needs design exploration first? → superpowers:brainstorming
│  ├─ Multi-step, needs a plan? → superpowers:writing-plans
│  ├─ Has a plan, ready to execute? → superpowers:executing-plans
│  ├─ 2+ independent tasks? → superpowers:dispatching-parallel-agents
│  └─ Single task, just do it → (no skill needed, execute directly)
│
├─ Review / audit / check quality?
│  ├─ PR review? → pr-review-toolkit:review-pr or code-review:code-review
│  ├─ Receiving review feedback? → superpowers:receiving-code-review
│  ├─ Security audit? → security-threat-model
│  ├─ Supply chain? → supply-chain-risk-auditor
│  └─ UI/UX audit? → web-design-guidelines
│
├─ Study / learn / steal from external project?
│  └→ steal (requires steal/* branch)
│
├─ Ship / commit / merge / PR?
│  ├─ About to claim "done"? → verification-gate (MANDATORY)
│  ├─ Create commit? → commit-commands:commit
│  ├─ Create PR? → commit-commands:commit-push-pr
│  ├─ Finish branch? → superpowers:finishing-a-development-branch
│  └─ CI is red? → babysit-pr
│
├─ Orchestrator operations?
│  ├─ Start/stop/status? → run / stop / status
│  ├─ System health? → doctor
│  ├─ View logs? → logs
│  ├─ Trigger collection? → collect
│  └─ Chat history? → bot-tg / bot-wx
│
├─ Document / file conversion?
│  ├─ PDF? → document-skills:pdf
│  ├─ Word? → document-skills:docx
│  ├─ PowerPoint? → document-skills:pptx
│  ├─ Excel/CSV? → document-skills:xlsx
│  └─ Markdown conversion? → markdown-converter
│
├─ Frontend / design / visual?
│  ├─ Web UI? → frontend-design:frontend-design
│  ├─ Presentation? → frontend-slides
│  ├─ Art/poster? → canvas-design
│  └─ HTML artifact? → web-artifacts-builder
│
├─ Write prompts / skills / plugins?
│  ├─ System prompt? → prompt-engineer (heavy) or prompt-maker:prompt-standard (light)
│  ├─ New skill? → superpowers:writing-skills
│  ├─ New plugin? → plugin-dev:create-plugin
│  └─ New hook? → plugin-dev:hook-development
│
└─ Web / browser / scraping?
   ├─ Scrape URL? → firecrawl-cli or summarize
   ├─ Browser automation? → playwright-skill or chrome-devtools-mcp:chrome-devtools
   └─ YouTube? → youtube-watcher
```

## Stage 2: Cross-cutting concerns

After routing to a primary skill, check if any of these also apply:

| Concern | Trigger | Add skill |
|---------|---------|-----------|
| Task completing | About to say "done" | verification-gate |
| Code was written | Any code change | (consider) superpowers:verification-before-completion |
| Multi-file plan | 3+ files changing | superpowers:writing-plans first |
| Git worktree needed | Needs isolation | superpowers:using-git-worktrees |
| TDD approach | Feature or bugfix | superpowers:test-driven-development |

## Routing Rules

1. **One primary skill per task.** Cross-cutting skills layer on top, but the primary skill drives the workflow.
2. **Deepest match wins.** If "PR review" matches both "review" and "PR", take the PR-specific route.
3. **When ambiguous, ask one question.** "Is this a bug fix or a new feature?" resolves 80% of routing ambiguity.
4. **No skill is also valid.** Simple, single-file edits don't need skill overhead. If the task takes < 2 minutes, just do it.
