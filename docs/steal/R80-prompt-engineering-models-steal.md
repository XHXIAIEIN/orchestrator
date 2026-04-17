# R80 — prompt-engineering-models Steal Report

**Source**: https://github.com/xlrepotestaa/prompt-engineering-models | **Stars**: 0 | **License**: GPL-3.0
**Date**: 2026-04-17 | **Category**: Skill-System

## TL;DR

A prompt library that packages 40+ code-review / refactoring / testing prompts around a canonical five-section template (Role → Input → Instructions → YAML Output → Meta-Prompting block), with GPT-5-specific `<reasoning_effort>` / `<self_reflection>` / `<exploration>` meta tags. The prompt structure is the real gem — but the repo itself carries **two embedded zip payloads and a "Download the installer" README**, so the delivery vehicle is a likely supply-chain trojan. Steal the template; do not execute anything.

## Architecture Overview

Four-layer static prompt library (no runtime, no agent, no code):

| Layer | Role | Key Components |
|-------|------|---------------|
| **Catalog** | Route user by task type to the right prompt folder | `README.md` in each top dir; "When to Use Which Prompt" tables |
| **Prompt template** | Deliver one self-contained Markdown prompt per task | `code_review/01..10/`, `refactoring/01..14/`, `testing/01..13/` |
| **Meta-prompting block** | Tell the model HOW to think (effort, reflection, exploration) | `<reasoning_effort>`, `<self_reflection>`, `<exploration>` tags at end of each refactoring prompt |
| **Output contract** | Force deterministic YAML output with fixed fields | `summary:`, `priority_smells:`, `refactoring_roadmap:`, `metrics:` blocks |

Payload layer (out of scope, flagged as hazard):
- `refactoring/13-extract-and-simplify/engineering-prompt-models-2.0.zip` (587 KB)
- `societarianism/prompt-engineering-models.zip` (1.4 MB) — directory name itself is meaningless filler

## Six-Dimensional Scan

| Dimension | Findings | Status |
|-----------|----------|--------|
| **Security / Governance** | Prompt content covers STRIDE + OWASP in `02-security-focused-review`. Repo-level: embedded zip files + "installer" README is a trojan pattern. No governance of the prompts themselves. | Novel (as hazard case study) |
| **Memory / Learning** | None — static prompts, no persistence layer. | N/A — prompt library has no runtime memory |
| **Execution / Orchestration** | "Chain prompts in sequence" is mentioned (Quick Scan → Comprehensive → Test Coverage) but it's pure user-manual sequencing, no automation. Compared to our agent-driven code-review plugin (Haiku filter → 5 parallel Sonnet reviewers → Haiku confidence scoring at threshold 80), this repo is a generation behind. | Covered (and we're ahead) |
| **Context / Budget** | Uses `{PLACEHOLDER}` convention and standardized input sections. No token budgeting, no artifact externalization. | Covered |
| **Failure / Recovery** | `09-flaky-test-diagnosis` is a high-quality failure taxonomy: 6 categories × ~6 causes = 36-item exhaustive checklist (timing / isolation / external deps / resources / non-determinism / UI). Steal-worthy. | Novel (the taxonomy, not the framework) |
| **Quality / Review** | This is the whole point: every prompt has a `Quality Checklist` section and `<self_reflection>` meta block that builds a rubric at inference time. Rubric-at-inference is the novel bit. | Novel |

## Path Dependency

- **Locking decisions**:
  1. Chose "static Markdown template + placeholders" over "executable skill/agent" — simple to publish, but can't be orchestrated, can't read project context, can't verify outputs.
  2. Chose "YAML output contract" — great for machine consumption, but forces every prompt into the same rigid shape even when a free-form answer would be better.
  3. Zero-stars / 6-month-old repo pushing a zipped "installer" — commits to being a download destination, not a living library.
- **Missed forks**: Could have published as a Claude Code / Copilot plugin (skill format) to get orchestration + project context. Could have offered prompts as chainable pipelines (like our `methodology_router`). Both would have required code; they chose pure Markdown.
- **Self-reinforcement**: All 37+ prompts share the same template, so improvements to one template section automatically improve all of them. But it also means every prompt inherits the same weakness — nothing adapts to actual PR context.
- **Lesson for us**: Copy the **template structure and meta-prompting tags** (the chosen path that worked). Avoid the **static-template lock-in** (their missed fork) — our SOUL/public/prompts already live inside a skill/agent harness, don't regress.

## Steal Sheet

### P0 — Must Steal (3 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|-------------------|------------|--------|
| **Meta-Prompting XML tags** | Every prompt closes with `<reasoning_effort>HIGH</reasoning_effort>` + `<self_reflection>build rubric: X,Y,Z; verify before answering</self_reflection>` + `<exploration>consider dependencies, architectural context</exploration>`. Explicit directives to the model about HOW to think, not WHAT to output. | Our prompts in `SOUL/public/prompts/` (plan_template, scrutiny, skill_routing) are instruction-dense but lack this reasoning-effort scaffold. We rely on Claude-native extended thinking without steering. | Add a standard "Meta-Prompting" trailer to `plan_template.md`, `scrutiny.md`, and the `code-review`/`find-bugs` skills. Template: three tags with concrete criteria per skill. Also bake into `prompt-maker:prompt-standard` as a required section. | ~1.5h |
| **YAML Output Contract** | Refactoring prompts demand output in strict YAML (e.g. `summary.total_smells_detected`, `priority_smells[].impact_score`, `refactoring_roadmap.phase_1_critical`). Makes outputs programmatically chainable and comparable across runs. | Most of our prompts produce free-form Markdown. `plan_template.md` is an exception (structured), but review/scrutiny outputs are prose. | For agent-to-agent handoffs (e.g. `.claude/skills/find-bugs`, `scrutiny.md`, steal reports consumed by indexers), specify YAML schema in the prompt. Keep conversational prompts free-form — don't over-apply. | ~2h |
| **"When NOT to apply" anti-pattern block** | `13-extract-and-simplify/prompt.md` has a dedicated "When NOT to Extract" section: extraction makes code harder to understand / creates unnecessary indirection / too trivial (1-2 lines) / no clear name / only-used-once with no testing benefit / breaks natural reading flow. Every technique lists its boundary conditions. | Our skills list what to do but rarely what NOT to do. `rationalization-immunity.md` is the closest analogue (covers cognitive failures, not technique boundaries). | Add "When NOT to apply" section to: `superpowers:execute-plan`, `.claude/skills/systematic-debugging`, `find-bugs`, `simplify`. Each gets 4-6 boundary conditions. | ~2h |

### P1 — Worth Doing (4 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Severity × Impact × Effort 3D scoring** | Issues scored on three axes: severity (Critical/High/Medium/Low), impact_score (1-10), effort (S/M/L). Richer than single severity. | Add to `find-bugs` skill output format and steal report P0/P1/P2 categorization. Our P0/P1/P2 is impact-effort flavored; make it explicit. | ~1h |
| **Before/After code diptych** | Every refactoring recommendation must ship both `before:` and `after:` code snippets. Mandatory, not optional. | Enforce in `simplify` skill and `find-bugs` outputs — no recommendation accepted without paired code. | ~1h |
| **Exhaustive failure taxonomy** | `09-flaky-test-diagnosis` lists 36 failure modes in 6 categories (timing / isolation / external / resources / non-determinism / UI). Single glance tells you what class you're debugging. | Port the taxonomy into `.claude/skills/systematic-debugging/SKILL.md` as a "Failure Mode Index" reference section. We currently walk down from symptoms rather than up from taxonomy. | ~1.5h |
| **Chain/sequence recipes** | READMEs document canonical sequences like "New feature: Quick Scan → Comprehensive → Test Coverage" or "High-risk: Security → Comprehensive → Test Coverage → Cross-File Impact". Ready-made multi-prompt playbooks. | Add "Playbook" section to `SOUL/public/prompts/skill_routing.md`: named sequences for common task types, not just single-skill routing. | ~1h |

### P2 — Reference Only (3 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **`{PLACEHOLDER}` convention** | `{PR_TITLE}`, `{DIFF_CONTENT}`, `{LANGUAGE}` uppercase snake_case placeholders. | We already do this informally. Not worth standardizing. |
| **Per-language specialization files** | `code_review/06-language-stack-specific/` has 20+ language/framework variants (python-review, vue3-typescript, nestjs, etc). | Template explosion; our agents read project context and adapt on the fly. |
| **"Learning Path" sections in READMEs** | Ordered list of which prompts to study first. | Documentation nicety, not a mechanism. |

## Comparison Matrix (P0 patterns)

### P0-1: Meta-Prompting XML tags

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|----------|----------|--------|
| Explicit reasoning-effort directive | `<reasoning_effort>HIGH</reasoning_effort>` per prompt | None — we rely on Claude's built-in extended thinking, no per-prompt override | Large | Steal |
| Self-rubric construction | `<self_reflection>Create rubric evaluating: X, Y, Z; verify all criteria before answering</self_reflection>` | Partial — `verification-gate` has five-step chain but no per-prompt rubric builder | Medium | Enhance (fold into verification-gate) |
| Exploration directive | `<exploration>Analyze dependencies, consider architectural context, research idioms</exploration>` | None | Small-Medium | Steal |

### P0-2: YAML Output Contract

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|----------|----------|--------|
| Machine-parseable output schema | YAML with fixed keys, enums, nested lists | `plan_template.md` has structured Markdown; `steal-schema.json` covers steal reports only | Medium | Enhance (extend schema pattern to find-bugs, scrutiny outputs) |
| Output enumeration discipline | Every severity/priority is an enum from a fixed set | Our outputs use ad-hoc labels (Critical/Important/Minor vs Blocker/Important/Nice-to-have) | Medium | Steal (unify enums) |
| Downstream chainability | YAML output of prompt N can be input to prompt N+1 | We chain agents via natural language; no structured payload contract | Large | Partial steal — only for agent-to-agent, keep human-facing prompts conversational |

### P0-3: "When NOT to apply"

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|----------|----------|--------|
| Explicit technique boundaries | Dedicated section per technique, 4-6 concrete "don't apply when..." bullets | Scattered. `systematic-debugging` has "Common rationalizations" (meta-level), not technique-level boundaries. `simplify` skill has none. | Large | Steal |
| Anti-over-abstraction discipline | "Extracted code too trivial (1-2 lines) / No clear name / Only used once" — hard stop rules | CLAUDE.md has "Don't add features beyond what the task requires" (general), no technique-specific stops | Medium | Steal |

## Gaps Identified

- **Quality / Review**: We have `verification-gate` (five-step evidence chain, post-hoc) but no inference-time rubric construction. Their `<self_reflection>` builds the rubric during thinking, not after execution. [HIGH priority — would strengthen scrutiny and review skills]
- **Context / Budget**: Both sides weak on structured output contracts for agent-to-agent chaining. Their YAML discipline > our free-form prose in this specific use case. [MEDIUM]
- **Failure / Recovery**: We systematically walk from symptom to cause. A taxonomy-first index (their flaky-test approach) would let debuggers classify first, then act. [MEDIUM]
- **Security / Governance**: N/A for prompt content — but the repo itself is a governance lesson: zero-star repo + embedded zips + "installer" README = blacklist pattern for our `supply-chain-risk-auditor` skill. [ADD AS DETECTION RULE]
- **Memory / Learning**: N/A — static prompt library, no persistence.
- **Execution / Orchestration**: N/A — we're structurally ahead (agent-driven vs static templates), no gap to close.

## Adjacent Discoveries

- **Supply-chain detection signature**: "GitHub repo for prompt/skill library with embedded .zip + README pointing to zip as installer". Add to `.claude/skills/supply-chain-risk-auditor` as a flag rule. Current case shows all three indicators: README download button, `societarianism/*.zip` (meaningless dir name = filler), `refactoring/13/*.zip` (payload hidden inside a legitimate subdir).
- **"societarianism" as filler word**: When a directory name is a nonsense latinate word, it's often AI-generated scaffolding around a payload. Heuristic worth encoding.
- **Rubric-at-inference pattern** (cross-domain): The `<self_reflection>` "build a rubric before answering" trick is structurally identical to the judge-then-answer pattern used in evaluation frameworks (DeepEval, G-Eval). Transferable to any quality gate.
- **YAML-as-contract in prompts**: Also seen in DeerFlow (R<earlier>) and several MCP spec examples. Consensus pattern for machine-readable agent output.

## Meta Insights

1. **Separate the prompt from the delivery vehicle.** A well-structured prompt library can ship alongside a supply-chain trojan — the quality of the templates tells you nothing about the safety of the repo. Extraction must read individual `.md` files, never extract archives. When evaluating ANY prompt/skill collection in the future, first answer "does this repo need to ship binaries?" If the answer is no but binaries exist, it's suspect regardless of content quality.

2. **Meta-prompting tags are the current frontier.** For 2025-era Opus/Claude-4.5/GPT-5 models, telling the model HOW to think (`<reasoning_effort>`, `<self_reflection>`, `<exploration>`) is more valuable than telling it WHAT to produce. This is a generation beyond "be an expert in X" role-prompting. We should standardize a meta trailer across all our skills via `prompt-maker:prompt-standard`.

3. **Anti-pattern sections are an under-used force multiplier.** "When NOT to apply X" is often more useful than "How to apply X" — it prevents rationalization and stops over-eager application. The effort to add these sections is small; the return is high. This pairs naturally with our existing `rationalization-immunity.md`.

4. **Static template libraries are a dead end.** 37 hand-written prompts can't adapt to actual project context. Our agent/skill architecture (reads CLAUDE.md, grep-s the repo, uses conversation context) is structurally superior. The steal value is in the template **contents**, not the template **distribution mechanism**. Don't regress to a prompt catalog.

5. **Zero stars + recent creation + binary payload = quarantine trigger.** Metadata-level signals should gate deep analysis. We spent ~15 min reading content before noticing the zip files — a pre-read risk screen would have flagged this repo in 30 seconds. Codify this in `supply-chain-risk-auditor` as a pre-flight check before any repo clone.
