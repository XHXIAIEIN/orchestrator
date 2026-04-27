---
name: claude-at
description: Launch a real interactive claude CLI session in a target directory (typically a worktree) with a pre-seeded prompt. Use when the current session cannot absorb the task context — e.g., N parallel worktree jobs that would blow the context window, or when you need the user to watch progress in a visible terminal. Each spawned session runs independently in its own Windows Terminal tab.
---

# claude-at

Fan-out to real claude sessions. One target = one new terminal tab.

## When to use

Use this skill when:
- You have N worktrees and each needs a non-trivial task; running them in-process would blow context
- Task is self-contained — the child session only needs (a) the prompt file, (b) the worktree, (c) its own CLAUDE.md
- You don't need tight output aggregation — child reports to disk (commit, file artifact, manifest), parent reads later

**Do NOT use for:**
- Small edits you can just make directly (one-off file change, trivial cherry-pick)
- Tasks that need parent's live state (open TodoWrite list, in-memory variables, etc.)
- Any task where children must coordinate mid-flight — subagents via Agent tool fit better there

## The launcher

`.claude/skills/claude-at/claude-at.sh <target-dir> <prompt-file> [title]`

What it does:
1. Validates that `target-dir` exists and `prompt-file` is readable
2. Uses Windows Terminal (`wt.exe -w 0 nt`) to open a new tab in the current WT window
3. Tab title defaults to `claude@<basename target-dir>`
4. Sets cwd to `target-dir`, runs `claude "$(cat <prompt-file>)"`
5. After claude exits, keeps the shell open (`exec bash`) so user can inspect

Fallback: if `wt.exe` is not on PATH, uses `cmd.exe /c start` to open a plain cmd window.

## Parallel dispatch pattern

```bash
# 1. Prepare one prompt file per target (parent does this)
mkdir -p .claude/tasks
for branch in $BRANCHES; do
  cat > .claude/tasks/${branch}.md <<EOF
You are in the worktree for $branch.

Your job: <self-contained instructions>.

Report done by: <observable artifact, e.g. a file in .claude/batch-collect/$branch/>.

Do NOT: git commit, git push, or touch any other worktree.
EOF
done

# 2. Fan out — one tab per target
for branch in $BRANCHES; do
  .claude/skills/claude-at/claude-at.sh \
    ".claude/worktrees/$branch" \
    ".claude/tasks/${branch}.md"
done

# 3. Poll for done markers from parent (or let user eyeball tabs)
while [ $(ls .claude/batch-collect/*/DONE 2>/dev/null | wc -l) -lt ${#BRANCHES[@]} ]; do
  sleep 10
done

# 4. Parent does the final merge step — no child touches git
```

## Design rules for child prompts

Every child prompt MUST:

1. **State the worktree identity explicitly** — "You are on branch X in worktree Y" — so the child doesn't misfire on wrong dir
2. **List exact file paths** — no "figure out what files belong here"; parent has that knowledge
3. **Forbid git operations** if parent handles merge — shared `.git/` will race on `index.lock`
4. **Specify a success artifact** — a file the child writes that parent can check for. No "report back verbally" — child's stdout is locked in its own tab
5. **Be self-contained** — child does NOT inherit parent context. Every piece of knowledge the child needs must be in the prompt or trivially derivable from cwd

## Caveats

- **Shared `.git/` serializes writes**: multiple children doing `git commit`, `git checkout`, or `git branch` against the same main repo will deadlock on index.lock. Children should either (a) stay in their own worktree and touch only their worktree's files, or (b) do no git ops at all and let parent aggregate.
- **No context inheritance**: spawned session reads fresh CLAUDE.md + skill list. It does NOT see the parent's conversation.
- **Permission prompts**: child may block on the trust dialog if cwd hasn't been trusted. Either pre-trust via `/add-dir`, or pass `--dangerously-skip-permissions` only in sandboxes. (The launcher does NOT add this flag by default.)
- **Orphan tabs**: if child hangs, user must close the tab manually. Launcher does not track PIDs.
- **Windows-only**: uses `wt.exe`. Port needed for macOS/Linux (use `osascript` / `gnome-terminal` respectively).

## Quick one-off (no prompt file)

For ad-hoc use, you can pass the prompt inline via stdin redirect:

```bash
echo "Summarize the last 5 commits on this branch" | \
  .claude/skills/claude-at/claude-at.sh .claude/worktrees/steal-eureka /dev/stdin
```

Or use a heredoc piped to the script's stdin — it reads `$2` with `cat`, so `/dev/stdin` works.
