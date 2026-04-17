# R80 — prompt-engineering-models Steal Report

**Source**: https://github.com/xlrepotestaa/prompt-engineering-models | **Stars**: 0 | **License**: GPL-3.0
**Date**: 2026-04-17 | **Category**: Skill-System

## TL;DR

A prompt library that packages 40+ code-review / refactoring / testing prompts around a canonical five-section template (Role → Input → Instructions → YAML Output → Meta-Prompting block), with GPT-5-specific `<reasoning_effort>` / `<self_reflection>` / `<exploration>` meta tags. The prompt structure is the real gem. The repo also ships two `.zip` files referenced from a README "Download" button — plausibly a convenience bundle for one-click skill import, but **we did not open them during this steal**. Treat as unaudited attachments, not as evidence of compromise. Steal the template; audit the zips before running anything from them.

> **Retrospective correction (2026-04-17)**: An earlier version of this TL;DR called the delivery vehicle a "likely supply-chain trojan" based on metadata signals alone (zero stars, embedded zip, README download link). That was a jump from heuristics to verdict without opening the archives. Corrected wording above; see Meta Insights #1 and #5 for the methodology update.

## Architecture Overview

Four-layer static prompt library (no runtime, no agent, no code):

| Layer | Role | Key Components |
|-------|------|---------------|
| **Catalog** | Route user by task type to the right prompt folder | `README.md` in each top dir; "When to Use Which Prompt" tables |
| **Prompt template** | Deliver one self-contained Markdown prompt per task | `code_review/01..10/`, `refactoring/01..14/`, `testing/01..13/` |
| **Meta-prompting block** | Tell the model HOW to think (effort, reflection, exploration) | `<reasoning_effort>`, `<self_reflection>`, `<exploration>` tags at end of each refactoring prompt |
| **Output contract** | Force deterministic YAML output with fixed fields | `summary:`, `priority_smells:`, `refactoring_roadmap:`, `metrics:` blocks |

Unaudited attachments (not opened during steal; open and inspect before use):
- `refactoring/13-extract-and-simplify/engineering-prompt-models-2.0.zip` (587 KB)
- `societarianism/prompt-engineering-models.zip` (1.4 MB)

## Six-Dimensional Scan

| Dimension | Findings | Status |
|-----------|----------|--------|
| **Security / Governance** | Prompt content covers STRIDE + OWASP in `02-security-focused-review`. Repo-level: two unaudited zip files referenced by a README "Download" button — plausibly a convenience bundle for bulk skill import. Contents not opened during this steal, so no basis to rule in or out. No governance of the prompts themselves. | N/A (prompt content only; zips unaudited) |
| **Memory / Learning** | None — static prompts, no persistence layer. | N/A — prompt library has no runtime memory |
| **Execution / Orchestration** | "Chain prompts in sequence" is mentioned (Quick Scan → Comprehensive → Test Coverage) but it's pure user-manual sequencing, no automation. Compared to our agent-driven code-review plugin (Haiku filter → 5 parallel Sonnet reviewers → Haiku confidence scoring at threshold 80), this repo is a generation behind. | Covered (and we're ahead) |
| **Context / Budget** | Uses `{PLACEHOLDER}` convention and standardized input sections. No token budgeting, no artifact externalization. | Covered |
| **Failure / Recovery** | `09-flaky-test-diagnosis` is a high-quality failure taxonomy: 6 categories × ~6 causes = 36-item exhaustive checklist (timing / isolation / external deps / resources / non-determinism / UI). Steal-worthy. | Novel (the taxonomy, not the framework) |
| **Quality / Review** | This is the whole point: every prompt has a `Quality Checklist` section and `<self_reflection>` meta block that builds a rubric at inference time. Rubric-at-inference is the novel bit. | Novel |

## Path Dependency

- **Locking decisions**:
  1. Chose "static Markdown template + placeholders" over "executable skill/agent" — simple to publish, but can't be orchestrated, can't read project context, can't verify outputs.
  2. Chose "YAML output contract" — great for machine consumption, but forces every prompt into the same rigid shape even when a free-form answer would be better.
  3. Zero-stars / 6-month-old repo with a zip "Download" button in the README — commits to being a download destination, not a living library.
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
- **Security / Governance**: N/A for prompt content. The repo-level lesson is procedural: when a prompt/skill repo ships binaries, audit them before extracting any content. Our `supply-chain-risk-auditor` should treat "unaudited zip in prompt repo" as a **triage trigger** (open and inspect), not as a blacklist signal. [ADD AS TRIAGE STEP]
- **Memory / Learning**: N/A — static prompt library, no persistence.
- **Execution / Orchestration**: N/A — we're structurally ahead (agent-driven vs static templates), no gap to close.

## Adjacent Discoveries

- **Unaudited-binary triage rule**: "Prompt/skill repo with embedded `.zip` referenced by README as a download" should trigger an **audit action** (open the archive, inspect contents, then decide), not a blacklist label. In this case the zips were never opened — the correct classification is "unknown", not "malicious". Add to `.claude/skills/supply-chain-risk-auditor` as a triage step, not a flag rule.
- **Rubric-at-inference pattern** (cross-domain): The `<self_reflection>` "build a rubric before answering" trick is structurally identical to the judge-then-answer pattern used in evaluation frameworks (DeepEval, G-Eval). Transferable to any quality gate.
- **YAML-as-contract in prompts**: Also seen in DeerFlow (R<earlier>) and several MCP spec examples. Consensus pattern for machine-readable agent output.

## Meta Insights

1. **Separate the prompt from the delivery vehicle — but don't confuse "unaudited" with "malicious".** A zip in a prompt repo is plausibly a convenience bundle (one-click skill import); it's also possibly a payload. Extraction should default to reading individual `.md` files rather than running archives — not because the archive is presumed hostile, but because contents are unknown until opened. The correct sequence when binaries exist: **audit first, label after**. An earlier version of this report jumped directly from "zip present" to "likely trojan" without opening the archives; that's speculation dressed as a finding.

2. **Meta-prompting tags are the current frontier.** For 2025-era Opus/Claude-4.5/GPT-5 models, telling the model HOW to think (`<reasoning_effort>`, `<self_reflection>`, `<exploration>`) is more valuable than telling it WHAT to produce. This is a generation beyond "be an expert in X" role-prompting. We should standardize a meta trailer across all our skills via `prompt-maker:prompt-standard`.

3. **Anti-pattern sections are an under-used force multiplier.** "When NOT to apply X" is often more useful than "How to apply X" — it prevents rationalization and stops over-eager application. The effort to add these sections is small; the return is high. This pairs naturally with our existing `rationalization-immunity.md`.

4. **Static template libraries are a dead end.** 37 hand-written prompts can't adapt to actual project context. Our agent/skill architecture (reads CLAUDE.md, grep-s the repo, uses conversation context) is structurally superior. The steal value is in the template **contents**, not the template **distribution mechanism**. Don't regress to a prompt catalog.

5. **Metadata signals gate triage, not verdict.** Zero stars + recent creation + embedded binaries raise "this deserves a pre-flight check" — not "this is malicious". The pre-flight action is: open the binaries, inspect, then decide. The original draft of this report shortcut the triage step and went straight to a label — that's the failure mode to codify against in `supply-chain-risk-auditor`. Mandate the audit step explicitly; block conclusions that skip it.
