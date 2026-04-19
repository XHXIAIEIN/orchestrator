# Plan: R83 P0#3 — Manus Typed Event Stream Architecture

> **Source pattern**: `docs/steal/R83-cl4r1t4s-steal.md` P0 #3 (Manus typed event_stream with 7 event types).
> **For executors**: follow `SOUL/public/prompts/plan_template.md` conventions. Every step has a copy-paste `verify` command.

## Goal

`grep -r 'event_type:' /c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/*.md | grep -E 'event_type: (memory|learning|experience|plan|observation|knowledge)' | wc -l` returns ≥ 20; and `python SOUL/tools/compiler.py --dry-run` produces output containing the string `--- KNOWLEDGE ---` (typed section header injected by compiler). Both conditions must hold simultaneously.

## Why This Scope

Manus is the only production agent with fully explicit typed event streams — Triple Validation scored this pattern 2/3 (cross-domain reproductions exist only weakly: Devin's planning/standard/edit modes are a loose analog, Codex AGENTS.md hierarchical scope is structurally similar but content-distinct). The single-project provenance is a real caveat.

We adopt it anyway for two reasons:

1. **R42 Evidence Tier System is already a partial event-type system in disguise.** Our memory files carry `type: feedback | user | project | reference` — that IS an event classification, just unformalized and not used at retrieval time. We're adding a second orthogonal dimension (`event_type`) that controls context loading rather than credibility weighting. These two dimensions serve different purposes and can coexist without conflict.

2. **The flat markdown problem is real and already biting us.** boot.md compiles all promoted learnings into a single flat section. Compiler can't distinguish "this is a persistent knowledge fact about the user" from "this is a transient observation from last week's debugging session." Typed frontmatter is the minimum viable fix — it enables targeted loading (code review session loads only `learning` events; onboarding loads `knowledge` events; daily digest loads `observation` events).

Simplicity pre-check: minimum viable = 1 schema file + frontmatter edits on memory files + 1 compiler function + 1 compiler output section + 1 test. This plan touches exactly those 5 categories. No runtime changes, no DB migration, no new services.

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `.claude/schemas/event-types.yaml` | Canonical enum definition for all 6 event_type values, mapping rules from existing `type` field, compatibility notes |
| Modify | `SOUL/tools/compiler.py` | Add `compile_typed_events_section()` function; call from `compile_boot()` to inject `--- KNOWLEDGE ---` / `--- LEARNING ---` / `--- OBSERVATION ---` sections |
| Create | `SOUL/tools/test_typed_events.py` | Dry-run compiler test: asserts 6 section headers present, asserts files missing `event_type` produce WARNING not ERROR |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_ai_hallucination_issue.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_breadth_first_output.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_bug_report.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_chrome_debug.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_commit_timing.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_delete_check_first.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_dispatch.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_docker_paths.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_expert_persona_trap.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_guard_respect.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_humor.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_launch_heartbeat.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_memory_not_patch.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_no_execution_menu.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_no_hallucinate.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_no_input_truncation.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_no_negative_rules.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_no_rube_goldberg.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_open_drafts_vscode.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_overconfidence.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_paths.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_persona.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_prompt_language.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_software_paths.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_steal_breadth.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_steal_depth.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_systematic_verification.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_tool_cascade.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_ui_style.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_writing_tone.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_wrong_target.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/user_profile_deep.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/user_claude_ai_personalization.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/user_claude_perception.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/user_music.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/user_projects_overview.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/user_subscription.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/user_x_likes.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/clawvard_token.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/reference_chrome_devtools.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/reference_claude_code_haha.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/reference_gstack_patterns.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/reference_local_models.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/reference_mac_mini_proxy.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/reference_new_teachers.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/reference_token_optimization.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/reference_vscode_ssh_wmi.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/reference_wt_automation.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal-r50-r57-batch.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal-r61-r75-deep-rescan.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round11_summary.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round13_chatdev.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round14_clawhub.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round15_entrix.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round16_lobehub.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round17_vibevoice.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round18_karpathy.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round19_researcher_skill.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round20_llm_council.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round21_hermes_agent.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round22_review_swarm.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round23_agent_browser.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round23_clawhub_humanizer.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round23_evolver.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round23_gog_clawhub.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round23_superdesign.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round23_superpowers.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round23_superpowers_tdd.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round25_steipete_agent_scripts.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round30_yoyo_evolve.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round31_claude_code_audit.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/steal_round32_agentlytics.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/bluetooth_stanmore.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/lol_locale.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/life-assistant-bar-setup.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/qqmusic-api-plugin-v2.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/lora_hard_cases.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/orchestrator_evolution.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/orchestrator_steal_consolidated.md` | Add `event_type: learning` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/project_analysis_opus_upgrade.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/project_capability_refactor.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/project_claw_desktop_shell.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/project_compose_vs_agent_md.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/project_construct3_llm.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/project_cvui.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/project_identity_clarification.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/project_prompt_standard_upgrade.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/project_wake_fix.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/security_hooks.md` | Add `event_type: knowledge` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/channel_layer_progress.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/construct3_rag_progress.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/engineering_subagent_impl_dispatch.md` | Add `event_type: observation` |
| Modify | `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/MEMORY.md` | Add YAML frontmatter block with `event_type: knowledge` (system env facts) |

---

## Phase 1: Define event_type Taxonomy + Schema

**Goal of this phase**: Establish the canonical 6-type enum and its mapping rules from existing `type` field, committed to a schema file that all subsequent phases reference.

### Task 1: Create schema file

- [ ] **Step 1.** Create `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/schemas/` directory and write `.claude/schemas/event-types.yaml` with the following content: a top-level `version: 1` key; a `types` section listing exactly 6 values (`memory`, `learning`, `experience`, `plan`, `observation`, `knowledge`) each with a `description` field (≤ 30 words), a `context_load_hint` field (when a new session should load this type), and a `manus_analog` field mapping to Manus's original vocabulary (`memory` → `Memory`, `learning` → `Datasource`, `experience` → `Observation`, `plan` → `Plan`, `observation` → `Observation`, `knowledge` → `Knowledge`); a `compatibility` section stating that `event_type` is independent of R42's `type` (user/feedback/project/reference) and `evidence` (verbatim/artifact/impression) fields — three orthogonal dimensions, no field overrides another; a `default_missing` field set to `null` (missing `event_type` generates WARNING at compile time, not ERROR — same principle as R42's evidence-tier default); a `mapping_from_type` section giving the mechanical rule for existing files: `type: feedback` → `event_type: observation`, `type: user` → `event_type: knowledge`, `type: reference` → `event_type: knowledge`, `type: project` → `event_type: observation`. Note in a comment that steal-* files override this rule: `steal_*` filename prefix → `event_type: learning` regardless of `type` field value.
  → verify: `test -f /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/schemas/event-types.yaml && python3 -c "import yaml; d=yaml.safe_load(open('/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/schemas/event-types.yaml')); assert len(d['types'])==6; print('OK:', list(d['types'].keys()))"`

### Task 2: Annotate SOUL/public/prompts files with event_type

The SOUL/public/prompts files have no YAML frontmatter today. This plan does NOT add frontmatter to them — they are prompt instruction files, not memory/event files. The `event_type` system applies only to memory files (the 92 files in the memory directory). This decision is recorded here to prevent scope creep.

ASSUMPTION: SOUL/public/prompts files are excluded from event_type tagging. Their function is to describe agent behavior (prompt instructions), not to represent typed events. If a future plan (e.g., P1 #9 AGENTS.md scoped instructions) adds frontmatter to prompts files, it should open a separate schema extension.

---

## Phase 2: Tag Existing Memory Files with event_type

**Goal of this phase**: Apply `event_type` to all 92 memory files by inserting one line into each file's existing YAML frontmatter block, immediately after the `type:` line.

All files in this phase use the mapping rule from Step 1's schema: `type: feedback` → `event_type: observation`; `type: user` → `event_type: knowledge`; `type: reference` → `event_type: knowledge`; `type: project` → `event_type: observation`; `steal_*` filename prefix → `event_type: learning`.

### Task 3: Tag feedback_* files (33 files) as event_type: observation

- [ ] **Step 2.** Open each of the 33 `feedback_*` files listed in the File Map. For each file, locate the line `type: feedback` inside the `---` frontmatter block and insert `event_type: observation` on the line immediately after it. The 33 files are: `feedback_ai_hallucination_issue.md`, `feedback_breadth_first_output.md`, `feedback_bug_report.md`, `feedback_chrome_debug.md`, `feedback_commit_timing.md`, `feedback_delete_check_first.md`, `feedback_dispatch.md`, `feedback_docker_paths.md`, `feedback_expert_persona_trap.md`, `feedback_guard_respect.md`, `feedback_humor.md`, `feedback_launch_heartbeat.md`, `feedback_memory_not_patch.md`, `feedback_no_execution_menu.md`, `feedback_no_hallucinate.md`, `feedback_no_input_truncation.md`, `feedback_no_negative_rules.md`, `feedback_no_rube_goldberg.md`, `feedback_open_drafts_vscode.md`, `feedback_overconfidence.md`, `feedback_paths.md`, `feedback_persona.md`, `feedback_prompt_language.md`, `feedback_software_paths.md`, `feedback_steal_breadth.md`, `feedback_steal_depth.md`, `feedback_systematic_verification.md`, `feedback_tool_cascade.md`, `feedback_ui_style.md`, `feedback_writing_tone.md`, `feedback_wrong_target.md`, `orchestrator_evolution.md`, `engineering_subagent_impl_dispatch.md`. All paths are under `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/`.
  → verify: `grep -l 'event_type: observation' /c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/feedback_*.md | wc -l | grep -qE '^3[01]$' && echo "observation count ok"`

### Task 4: Tag user_* and reference_* files (16 files) as event_type: knowledge

- [ ] **Step 3.** Open each of the 16 `user_*` and `reference_*` files plus `clawvard_token.md`, `bluetooth_stanmore.md`, `lol_locale.md`, `life-assistant-bar-setup.md`, and `security_hooks.md` listed in the File Map. For each file, locate `type: user` or `type: reference` inside the `---` frontmatter block and insert `event_type: knowledge` on the line immediately after it. The files are: `user_profile_deep.md`, `user_claude_ai_personalization.md`, `user_claude_perception.md`, `user_music.md`, `user_projects_overview.md`, `user_subscription.md`, `user_x_likes.md`, `clawvard_token.md`, `reference_chrome_devtools.md`, `reference_claude_code_haha.md`, `reference_gstack_patterns.md`, `reference_local_models.md`, `reference_mac_mini_proxy.md`, `reference_new_teachers.md`, `reference_token_optimization.md`, `reference_vscode_ssh_wmi.md`, `reference_wt_automation.md`, `bluetooth_stanmore.md`, `lol_locale.md`, `life-assistant-bar-setup.md`, `security_hooks.md`. All under `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/`.
  → verify: `grep -rl 'event_type: knowledge' /c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/ | wc -l | grep -qE '^[2-9][0-9]$' && echo "knowledge count ok (expect ≥20)"`

### Task 5: Tag steal_* files (25 files) as event_type: learning

- [ ] **Step 4.** Open each of the 25 steal-related files listed in the File Map. For each file, locate the `type:` line inside the `---` frontmatter block and insert `event_type: learning` on the line immediately after it. Note: these files override the default type→event_type mapping because their filename prefix (`steal_*` or `steal-*`) takes precedence per the schema rule. The files are: `steal-r50-r57-batch.md`, `steal-r61-r75-deep-rescan.md`, `steal_round11_summary.md`, `steal_round13_chatdev.md`, `steal_round14_clawhub.md`, `steal_round15_entrix.md`, `steal_round16_lobehub.md`, `steal_round17_vibevoice.md`, `steal_round18_karpathy.md`, `steal_round19_researcher_skill.md`, `steal_round20_llm_council.md`, `steal_round21_hermes_agent.md`, `steal_round22_review_swarm.md`, `steal_round23_agent_browser.md`, `steal_round23_clawhub_humanizer.md`, `steal_round23_evolver.md`, `steal_round23_gog_clawhub.md`, `steal_round23_superdesign.md`, `steal_round23_superpowers.md`, `steal_round23_superpowers_tdd.md`, `steal_round25_steipete_agent_scripts.md`, `steal_round30_yoyo_evolve.md`, `steal_round31_claude_code_audit.md`, `steal_round32_agentlytics.md`, `orchestrator_steal_consolidated.md`. Also tag `qqmusic-api-plugin-v2.md` and `lora_hard_cases.md` as `event_type: learning` (these are project-derived learning documents). All under `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/`.
  → verify: `grep -rl 'event_type: learning' /c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/ | wc -l | grep -qE '^2[0-9]$' && echo "learning count ok (expect ≥24)"`

### Task 6: Tag project_* and misc observation files (9 files) as event_type: observation

- [ ] **Step 5.** Open each of the 9 `project_*` files plus `channel_layer_progress.md`, `construct3_rag_progress.md` listed in the File Map. For each file, locate `type: project` inside the `---` frontmatter block and insert `event_type: observation` on the line immediately after it. The files are: `project_analysis_opus_upgrade.md`, `project_capability_refactor.md`, `project_claw_desktop_shell.md`, `project_compose_vs_agent_md.md`, `project_construct3_llm.md`, `project_cvui.md`, `project_identity_clarification.md`, `project_prompt_standard_upgrade.md`, `project_wake_fix.md`, `channel_layer_progress.md`, `construct3_rag_progress.md`. All under `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/`.
  → verify: `grep -l 'event_type: observation' /c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/project_*.md | wc -l | grep -qE '^[89]$' && echo "project observation count ok"`

### Task 7: Tag MEMORY.md (system index) as event_type: knowledge

- [ ] **Step 6.** Read `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/MEMORY.md`. If it has a `---` YAML frontmatter block at the top, insert `event_type: knowledge` as the last field before the closing `---`. If it has no frontmatter block, prepend `---\nevent_type: knowledge\n---\n` to the file. MEMORY.md contains environment facts (paths, tool locations, environment info) — this is persistent knowledge, hence `event_type: knowledge`.
  → verify: `grep -q 'event_type: knowledge' /c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/MEMORY.md && echo "MEMORY.md tagged"`

### Task 8: Verify total tagged count meets Goal threshold

- [ ] **Step 7.** Run the coverage check: count all memory files with any `event_type:` field.
  - depends on: steps 2, 3, 4, 5, 6
  → verify: `grep -rl 'event_type:' /c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/ | wc -l | tee /dev/stderr | xargs -I{} test {} -ge 20 && echo "PASS: ≥20 files tagged"`

---

## Phase 3: Modify Compiler to Inject Typed Sections + Verify

**Goal of this phase**: `compile_boot()` reads event_type from memory files (via `extract_memory_rules` or a new dedicated reader), groups items by type, and injects 3 section headers (`--- KNOWLEDGE ---`, `--- LEARNING ---`, `--- OBSERVATION ---`) into the boot.md output.

### Task 9: Add typed memory reader to compiler

- [ ] **Step 8.** Add function `read_typed_memory_sections(path: Optional[Path] = None) -> dict[str, list[str]]` to `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/tools/compiler.py`, after the `extract_memory_rules()` function (line ~638). The function: (a) reads MEMORY.md from `path or MEMORY_INDEX`; (b) scans all sibling `*.md` files in the same directory; (c) for each file, reads its YAML frontmatter block (`---...---`) using `re.search(r'^---\n(.*?)\n---', content, re.DOTALL)` and extracts `event_type` with `re.search(r'^event_type:\s*(\S+)', fm_block, re.MULTILINE)`; (d) if `event_type` is absent, prints `[compiler] WARNING: {filename} missing event_type — skipping from typed sections` to stderr and continues (does NOT raise); (e) groups the file's `description` field (first YAML `description:` value) into a `dict[str, list[str]]` keyed by event_type; (f) returns the dict. The function must not crash if the memory dir doesn't exist (return empty dict).
  → verify: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python3 -c "from SOUL.tools.compiler import read_typed_memory_sections; d=read_typed_memory_sections(); print({k: len(v) for k,v in d.items()})"`

### Task 9b: Add typed section formatter to compiler

- [ ] **Step 9.** Add function `format_typed_events_section(typed: dict[str, list[str]]) -> str` to `SOUL/tools/compiler.py`, immediately after `read_typed_memory_sections()`. The function: (a) defines the 3 sections to include in boot.md in this order: `knowledge`, `learning`, `observation`; (b) for each type that has ≥ 1 entry in `typed`, outputs `--- {TYPE.upper()} ---\n` followed by a bullet list of `description` strings (one per file, truncated to 80 chars if longer, prefixed `- `); (c) skips types with zero entries silently; (d) if `typed` is empty, returns an empty string; (e) prepends one header line: `## Typed Memory Index\n<!-- Auto-generated by compiler.py from event_type frontmatter. Read .claude/context/learnings.md for full learnings detail. -->\n`.
  - depends on: step 8
  → verify: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python3 -c "from SOUL.tools.compiler import read_typed_memory_sections, format_typed_events_section; s=format_typed_events_section(read_typed_memory_sections()); print('KNOWLEDGE' in s, 'LEARNING' in s, 'OBSERVATION' in s)"`

### Task 10: Wire typed section into compile_boot()

- [ ] **Step 10.** In `compile_boot()` in `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/tools/compiler.py`, locate the assembly of the `boot` f-string (around line 692 where `boot = f"""# SOUL Boot Image...` begins). Add a step 6 before the string assembly: `typed_events = format_typed_events_section(read_typed_memory_sections())`. Then insert `{typed_events}\n\n---\n\n` between the `## Learnings` section and the `## 按需加载` section in the boot f-string. The `## Learnings` section ends with `</reference>` and is followed by `---`. Insert the typed events block between the closing `---` of Learnings and the `## 按需加载` header. If `typed_events` is empty (memory dir missing), the insertion produces no output.
  - depends on: step 9
  → verify: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python3 SOUL/tools/compiler.py --dry-run 2>/dev/null | grep -q '--- KNOWLEDGE ---' && echo "KNOWLEDGE section present in dry-run"`

### Task 11: Write and run the test

- [ ] **Step 11.** Create `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/tools/test_typed_events.py` with 4 test cases using only stdlib (no pytest dependency — run with `python3 test_typed_events.py`):
  1. **Test `read_typed_memory_sections` with real memory dir**: assert `len(result.get('observation', [])) >= 10` and `len(result.get('learning', [])) >= 10` and `len(result.get('knowledge', [])) >= 5`.
  2. **Test `format_typed_events_section` with synthetic data**: call with `{'knowledge': ['User prefers X', 'Ref: Y'], 'learning': ['Steal R11: Z'], 'observation': []}` — assert output contains `--- KNOWLEDGE ---` and `--- LEARNING ---` and does NOT contain `--- OBSERVATION ---` (zero-entry type omitted).
  3. **Test WARNING for missing event_type**: create a temp directory with one synthetic `.md` file that has `---\nname: test\ntype: feedback\n---\n` (no event_type). Call `read_typed_memory_sections(path=tmp_dir / 'MEMORY.md')` with `MEMORY.md` absent. Capture stderr. Assert the word `WARNING` appears in stderr for the synthetic file.
  4. **Test dry-run compiler produces section headers**: call `compile_boot(dry_run=True)` via `subprocess.run(['python3', 'SOUL/tools/compiler.py', '--dry-run'], capture_output=True, text=True, cwd='/d/Users/Administrator/Documents/GitHub/orchestrator')` and assert `'--- KNOWLEDGE ---'` in stdout.
  Each test prints `PASS: <name>` or `FAIL: <name>: <reason>`. Script exits 1 if any test fails.
  - depends on: steps 8, 9, 10
  → verify: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python3 SOUL/tools/test_typed_events.py | tee /dev/stderr | grep -c '^PASS' | xargs -I{} test {} -eq 4 && echo "all 4 tests pass"`

### Task 12: Run full compiler and confirm output

- [ ] **Step 12.** Run the compiler in dry-run mode and confirm all 3 typed section headers and the Goal condition are both satisfied in a single pass.
  - depends on: steps 10, 11
  → verify: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python3 SOUL/tools/compiler.py --dry-run 2>/dev/null | grep -E '--- (KNOWLEDGE|LEARNING|OBSERVATION) ---' | sort | uniq | wc -l | xargs -I{} test {} -ge 2 && echo "PASS: typed sections in dry-run"`

---

## Phase Gates

### Gate 1: Plan → Implement

- [ ] Every step has action verb + specific target + verify command
- [ ] No banned placeholder phrases (checked against Iron Rule table)
- [ ] Dependencies explicit on every multi-step task
- [ ] Total steps: 12 (within 5–30 range)
- [ ] Simplicity pre-check documented (see "Why This Scope")
- [ ] Owner review: **not required** (all memory file edits insert one YAML line; compiler changes are additive; all changes are easily reverted by removing the `event_type:` lines and reverting compiler.py)
- [ ] ASSUMPTION: The memory dir path `/c/Users/test/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory/` is stable across executor sessions. If it changes, compiler's `_find_memory_dir()` auto-discovers the correct path — the schema and tagging still apply.

### Gate 2: Implement → Verify

- [ ] Steps 2–6 verify commands all return exit 0 with the expected count assertions
- [ ] Step 7 confirms ≥ 20 total tagged files
- [ ] Step 10 dry-run shows `--- KNOWLEDGE ---` in compiler output
- [ ] Step 11 test script shows `PASS` on all 4 cases
- [ ] `git diff SOUL/tools/compiler.py` contains only additions of `read_typed_memory_sections`, `format_typed_events_section`, and the 3-line wire-up in `compile_boot` — no deletions of existing logic

### Gate 3: Verify → Commit

- [ ] Pre-commit hook passes (no protected-file edits — `.claude/boot.md` and `CLAUDE.md` are untouched; compiler.py is not protected)
- [ ] `git diff --stat` matches the File Map: only `.claude/schemas/event-types.yaml`, `SOUL/tools/compiler.py`, `SOUL/tools/test_typed_events.py`, and memory `*.md` files
- [ ] Commit message: `feat(memory): R83 P0#3 — Manus typed event stream: event_type frontmatter + compiler section injection`
- [ ] Cross-reference in commit body: `Refs: docs/steal/R83-cl4r1t4s-steal.md:47 (P0 #3)`

---

## Dependencies on Other R83 Plans

| Slug | Relationship to this plan |
|------|--------------------------|
| `R83-dia-trust-tagging` (P0#1) | **Independent**. P0#1 adds EXTERNAL_CONTENT tag grammar to steal skill; P0#3 adds event_type frontmatter to memory files. No shared files. P0#1 creates `.claude/hooks/content-trust.sh`; P0#3 modifies `SOUL/tools/compiler.py` — no overlap. Can ship in any order. |
| `R83-droid-phase-gate` (P0#2) | **Independent at file level**. P0#2 adds `.claude/hooks/phase-gate.sh` and `.claude/phase-state.json`; P0#3 adds `.claude/schemas/event-types.yaml` and `SOUL/tools/compiler.py` changes. No shared files. However, P0#2's phase-state concept is conceptually related — if phase-gate eventually enforces "can't write memory files without correct event_type", it would depend on the schema from this plan (P0#3). Ship P0#3 first to establish the schema as the dependency anchor. |
| `R83-manus-typed-events` (P0#3) | **This plan**. |
| `R83-droid-intent-gate` (P0#4) | **Independent**. P0#4 adds intent declaration grammar (`[INTENT: diagnostic | implementation | spec]`) to response hooks; P0#3 adds event_type to memory frontmatter. The two orthogonal tagging schemes (intent for turn-level, event_type for memory-level) do not share files. |
| `R83-anti-fabrication` (P0#5) | **Soft dependency on schema alignment**. P0#5 adds a `fabrication` row to `SOUL/public/prompts/rationalization-immunity.md`. If any future step promotes rationalization-immunity.md to a typed memory file, it should receive `event_type: knowledge` (it encodes persistent behavioral rules). This plan does NOT tag SOUL/public/prompts files — that exclusion is documented in Task 2. If P0#5 implementation touches memory files directly, coordinate to use the schema from Step 1 of this plan. |

---

## Known Limits / Deferred Items

- **`memory` and `experience` event types are defined in the schema but not assigned to any existing file.** These are reserved for future structured writes: `memory` for explicit "remember this" saves; `experience` for JSONL experience records promoted to markdown. The compiler's `format_typed_events_section()` will simply output empty sections for these types (or omit them if zero entries), which is correct behavior.

- **`plan` event type is defined in the schema but not assigned.** Plans live in `docs/superpowers/plans/` as tracked git files, not in the Claude memory dir. If a future plan promotes plan files to typed memory, extend the compiler's `read_typed_memory_sections()` to also scan the plans directory for `event_type: plan`.

- **SOUL/public/prompts files are intentionally excluded from event_type tagging.** They are agent instruction documents, not memory events. This boundary is enforced by the compiler — `read_typed_memory_sections()` reads only from the memory dir.

- **The compiler change is additive-only.** Existing `extract_memory_rules()`, `promoted_learnings()`, and all context pack functions are unchanged. If `read_typed_memory_sections()` throws, `compile_boot()` catches the exception and continues (typed section is empty) — the existing boot.md sections are unaffected.

- ASSUMPTION: `yaml.safe_load` is available in the compiler's Python environment. The schema verification command in Step 1 uses it. If PyYAML is absent, use `re` parsing instead (the schema file is simple enough for regex extraction). Resolve in Step 1.

---

## Effort Estimate

| Task | Steps | Estimate |
|------|-------|----------|
| Task 1: Schema file | 1 | 20 min |
| Task 3: Tag 33 feedback_* files | 1 | 45 min |
| Task 4: Tag 21 user_*/reference_* files | 1 | 30 min |
| Task 5: Tag 25 steal_* files | 1 | 35 min |
| Task 6: Tag 11 project_* files | 1 | 20 min |
| Task 7: Tag MEMORY.md | 1 | 10 min |
| Task 8: Coverage check | 1 | 5 min |
| Task 9: `read_typed_memory_sections()` | 1 | 40 min |
| Task 9b: `format_typed_events_section()` | 1 | 20 min |
| Task 10: Wire into `compile_boot()` | 1 | 20 min |
| Task 11: Test file (4 cases) | 1 | 40 min |
| Task 12: Final dry-run verification | 1 | 10 min |
| **Total** | **12** | **~5h** |
