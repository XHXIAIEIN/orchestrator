# Documentation & Knowledge Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate 10 rounds of steal-sheet research into a unified architecture knowledge base, slim down CLAUDE.md, clean up MEMORY.md, and produce a prioritized roadmap.

**Architecture:** Three-layer restructure — knowledge consolidation (PATTERNS.md), document realignment (CLAUDE.md/MEMORY.md), and strategic roadmap (ROADMAP.md). All under new `docs/architecture/` directory.

**Spec:** `docs/superpowers/specs/2026-03-28-docs-restructure-design.md`

---

## Task 1: Create docs/architecture/ skeleton

**Files:**
- Create: `docs/architecture/README.md`
- Create: `docs/architecture/modules/` (empty dir via .gitkeep)

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p docs/architecture/modules
```

- [ ] **Step 2: Write README.md — architecture overview**

Content: system overview paragraph, ASCII architecture diagram (collectors → storage → analysis → governance → channels), module index table pointing to modules/, design philosophy (ABC injection, 三省六部, SOUL inheritance), pointers to PATTERNS.md and ROADMAP.md.

Source material:
- `src/` directory listing for module names
- `SOUL/README.md` for design philosophy
- `departments/` for governance model
- `.claude/boot.md` lines 60-80 for management philosophy summary

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/
git commit -m "docs(architecture): create skeleton with README overview"
```

---

## Task 2: Write PATTERNS.md — the master pattern table

**Files:**
- Create: `docs/architecture/PATTERNS.md`

**Source material (ALL of these must be read):**
- Memory files: `orchestrator_steal_sheet.md` through `orchestrator_steal_sheet_10.md` (10 files)
- Docs: `docs/superpowers/steal-sheets/*.md` (3 files)
- Archive: `tmp/research-2026-03-22/STEAL-SHEET.md`
- Original research: `SOUL/public/research-sycophancy-split.md` (for Fact-Expression Split)

**Structure:**
- Overview stats (total patterns, implemented/designed/pending counts)
- 8 themed sections: Safety, Reliability, Performance, Intelligence, Resources, Perception, Orchestration, Human-AI
- Each pattern: one row with `#`, `Pattern`, `Source`, `Status` (✅/📐/🔲/⏸️), `Location`, `Notes`
- De-duplicate: merge Loop Detection (5 variants), Cost Tracking (3 variants), Context Compression (3 variants) into single entries with sub-notes
- Cross-reference table at bottom: Source Project → Pattern IDs

**Verify against code:**
- For every ✅ pattern, grep the codebase to confirm the file exists at the stated location
- For every 📐 pattern, confirm the spec/plan file exists in `docs/superpowers/`

- [ ] **Step 1: Read all 10 memory steal sheets + 3 docs steal sheets + STEAL-SHEET.md**
- [ ] **Step 2: Build de-duplicated pattern list organized by 8 themes**
- [ ] **Step 3: Cross-check ✅ patterns against actual codebase files**
- [ ] **Step 4: Write PATTERNS.md**
- [ ] **Step 5: Commit**

```bash
git add docs/architecture/PATTERNS.md
git commit -m "docs(architecture): add PATTERNS.md — 90+ patterns with status tracking"
```

---

## Task 3: Write ROADMAP.md — prioritized implementation plan

**Files:**
- Create: `docs/architecture/ROADMAP.md`

**Source material:**
- `docs/superpowers/specs/2026-03-28-docs-restructure-design.md` (Layer 3 section)
- `SOUL/public/research-sycophancy-split.md` lines 148-153 (4 pending items)
- `docs/superpowers/plans/*.md` (5 plans that are written but not started)
- PATTERNS.md (for 🔲 pattern IDs)

**Structure:**
- Sprint 1: Quick Wins (6 items, low effort high value)
- Sprint 2: Design Required (6 items, need spec first)
- Sprint 3: Strategic Reserve (8+ items)
- Already Designed section (5 existing plans not yet started)
- Fact-Expression Split pending items (4 items)
- Each item: Pattern name, source, value/effort rating, target file, dependency

- [ ] **Step 1: Write ROADMAP.md with all sprint tables**
- [ ] **Step 2: Commit**

```bash
git add docs/architecture/ROADMAP.md
git commit -m "docs(architecture): add ROADMAP.md — 3-sprint prioritized plan"
```

---

## Task 4: Extract desktop_use docs from CLAUDE.md

**Files:**
- Create: `docs/architecture/modules/desktop-use.md`
- Modify: `CLAUDE.md` (replace 87-line desktop_use section with 3-line pointer)

- [ ] **Step 1: Read CLAUDE.md lines 40-126 (desktop_use section)**
- [ ] **Step 2: Write `docs/architecture/modules/desktop-use.md`**

Copy the full desktop_use section (types table, ABCs, detection stages, perception layers, patterns, TODOs, working rules) into the new file with a proper title.

- [ ] **Step 3: Slim CLAUDE.md**

Replace lines 40-126 with:

```markdown
### desktop_use — GUI Automation Module
See `docs/architecture/modules/desktop-use.md` for full architecture (types, ABCs, detection stages, perception layers, working rules).
Key rule: Use `/analyze-ui` skill for testing, don't hand-write mss/ctypes screenshot code.
```

- [ ] **Step 4: Verify CLAUDE.md is now ~60 lines**
- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/architecture/modules/desktop-use.md
git commit -m "docs: extract desktop_use architecture from CLAUDE.md to docs/architecture/"
```

---

## Task 5: Move Fact-Expression Split to docs/architecture/

**Files:**
- Move: `SOUL/public/research-sycophancy-split.md` → `docs/architecture/fact-expression-split.md`
- Modify: `SOUL/public/research-sycophancy-split.md` (leave redirect note)

- [ ] **Step 1: Copy to new location**

```bash
cp SOUL/public/research-sycophancy-split.md docs/architecture/fact-expression-split.md
```

- [ ] **Step 2: Replace original with redirect**

Write to `SOUL/public/research-sycophancy-split.md`:
```markdown
# Moved

This document has been moved to `docs/architecture/fact-expression-split.md` as part of the 2026-03-28 documentation restructure.
```

- [ ] **Step 3: Commit**

```bash
git add SOUL/public/research-sycophancy-split.md docs/architecture/fact-expression-split.md
git commit -m "docs: move fact-expression-split to docs/architecture/"
```

---

## Task 6: Consolidate memory steal sheets

**Files:**
- Create: `memory/orchestrator_steal_consolidated.md` (in Claude memory dir)
- Modify: `memory/MEMORY.md`
- Move: 10 `memory/orchestrator_steal_sheet*.md` → `.trash/2026-03-28-steal-sheet-consolidation/`

Memory dir: `C:/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/`

- [ ] **Step 1: Create orchestrator_steal_consolidated.md**

Structure: frontmatter (name, description, type: reference) + per-round 3-5 line summary (source, stars, core patterns, implementation ratio) + pointer to `docs/architecture/PATTERNS.md` for full table.

- [ ] **Step 2: Update MEMORY.md**

Replace the 10 steal_sheet lines (99-109) with:

```markdown
- [orchestrator_steal_consolidated.md](orchestrator_steal_consolidated.md) — 10 轮偷师总索引（56 项目 / 90+ 模式），详细模式表见 `docs/architecture/PATTERNS.md`
```

Also keep reference_new_teachers.md and reference_gstack_patterns.md as-is (they're reference type, not steal sheets).

- [ ] **Step 3: Move 10 original files to .trash/**

```bash
mkdir -p .trash/2026-03-28-steal-sheet-consolidation
# mv each orchestrator_steal_sheet*.md to .trash/
```

- [ ] **Step 4: Commit (project repo for .trash/ only)**

```bash
git add .trash/2026-03-28-steal-sheet-consolidation/
git commit -m "chore: archive 10 steal sheet memory files (consolidated)"
```

Note: memory files are outside the git repo, so only .trash/ needs committing.

---

## Task 7: Archive tmp/research-2026-03-22/

**Files:**
- Move: `tmp/research-2026-03-22/` → `docs/research-archive/2026-03-22-orchestrator-survey/`

- [ ] **Step 1: Move directory**

```bash
mkdir -p docs/research-archive
mv tmp/research-2026-03-22 docs/research-archive/2026-03-22-orchestrator-survey
```

- [ ] **Step 2: Commit**

```bash
git add docs/research-archive/
git commit -m "docs: archive round-1 research to docs/research-archive/"
```

---

## Task 8: Write remaining module docs (lightweight)

**Files:**
- Create: `docs/architecture/modules/governance.md`
- Create: `docs/architecture/modules/channels.md`
- Create: `docs/architecture/modules/collectors.md`
- Create: `docs/architecture/modules/storage.md`
- Create: `docs/architecture/modules/browser-runtime.md`

Each module doc: ~30-50 lines. Structure: Purpose, Key Files table, Architecture Pattern, Key Types/ABCs. Source: read the actual module's `__init__.py`, key files, and any existing specs in `docs/superpowers/specs/`.

These are lightweight reference docs, not full specs. They answer "what is this module and where are its key files?"

- [ ] **Step 1: Read src/governance/, src/channels/, src/collectors/, src/storage/, src/core/browser_*.py**
- [ ] **Step 2: Write all 5 module docs**
- [ ] **Step 3: Commit**

```bash
git add docs/architecture/modules/
git commit -m "docs(architecture): add module reference docs for governance, channels, collectors, storage, browser"
```

---

## Verification

After all tasks complete:

- [ ] `CLAUDE.md` is ~60 lines (down from 131)
- [ ] `docs/architecture/README.md` exists with module index
- [ ] `docs/architecture/PATTERNS.md` has 90+ patterns with status
- [ ] `docs/architecture/ROADMAP.md` has 3 sprints
- [ ] `docs/architecture/modules/` has 6 module docs
- [ ] `docs/architecture/fact-expression-split.md` exists
- [ ] `memory/MEMORY.md` steal-sheet entries: 1 (down from 10)
- [ ] `memory/orchestrator_steal_consolidated.md` exists
- [ ] `.trash/2026-03-28-steal-sheet-consolidation/` has 10 files
- [ ] `docs/research-archive/2026-03-22-orchestrator-survey/` exists
- [ ] Zero information loss — all originals recoverable
