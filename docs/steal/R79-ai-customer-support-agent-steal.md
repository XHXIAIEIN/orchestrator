# R79 — alexandros-alexakis/ai-customer-support-agent Steal Report

**Source**: https://github.com/alexandros-alexakis/ai-customer-support-agent | **Stars**: 0 | **License**: none declared
**Date**: 2026-04-17 | **Category**: Specific Module (customer-support Tier-1 triage skeleton + prompt system)
**Repo age**: 2 days | **Size**: ~2,000 LOC Python + ~2,400 lines markdown

---

## TL;DR

A 2-day-old skeleton that solves one very specific problem cleanly: **how do you let an LLM answer a customer when the consequences of "acting autonomously on the wrong ticket" are real money and real liability?** The answer it commits to is a hard separation: a deterministic rule-based triage engine makes the escalate/route/priority decisions and produces a `ResponseStrategy`; the LLM only generates the natural-language wording. The decision layer is fully auditable; the LLM layer is deliberately boxed in with hard-escalate triggers, prohibited-action lists, and a fatal-error QA rubric.

Why it's worth stealing from despite being tiny and unstarred: the author did the *boring* work we keep skipping — writing down the rules that a prompt alone cannot enforce.

---

## Architecture Overview

Three strictly separated layers:

```
Layer 1 — Decision layer (deterministic, auditable, unit-tested)
  engine/classifier.py    keyword → intent + tone + confidence + flags
  engine/prioritizer.py   rules table → P1..P5 + SLA
  engine/escalation.py    hard triggers + soft triggers + routing table
  engine/response_router.py intent+escalation → ResponseStrategy (tone/opening/action/collect)
  engine/pipeline.py      runs all 4, logs structured JSON per step

Layer 2 — Knowledge layer (semantic, sync'd from markdown)
  rag/kb_sync.py          chunks kb/*.md by ## headers → ChromaDB (all-MiniLM-L6-v2)
  rag/retriever.py        cosine-sim query, MIN_RELEVANCE_SCORE=0.4 floor

Layer 3 — Generation layer (non-deterministic, boxed in)
  system-prompt.md        behavior contract: scope / tone / prohibited actions
  llm_client.py           mock-mode fallback when ANTHROPIC_API_KEY absent
  multilingual/language_handler.py   Claude-detected lang prepended to sysprompt

Cross-cutting
  feedback/gap_tracker.py   low-confidence / UNKNOWN cases → gaps.json for KB review
  feedback/feedback_store.py QA corrections w/ critical|high|standard priority
  evaluation/scripts/*      synthetic tickets → pipeline → results.json → report.md
  qa/qa-framework.md        100-pt rubric × 5 categories + Fatal Errors (auto-zero)
```

Key architectural commitment: **only the generation layer is non-deterministic**. Everything that decides *what to do* is rules the ops team can read and argue with. The LLM decides only *how to say it*.

---

## Six-Dimensional Scan

| Dimension | Status | Finding |
|-----------|--------|---------|
| **Security / Governance** | Strong | HMAC-SHA256 webhook signature verification (`integrations/zendesk_webhook.py:26-46`); WEBHOOK_SECRET explicitly warns when unset. Prohibited-actions list in system-prompt.md enforces epistemic constraints (never promise refund, never ask for password, never interpret TOS). |
| **Memory / Learning** | Moderate | Two-channel feedback: `gap_tracker` for where-we-failed-to-classify, `feedback_store` for where-QA-overrode-us. Both are JSON-file local, both have `by_reason` / `by_intent` / `by_priority` aggregators for weekly review. No closed-loop auto-update to KB. |
| **Execution / Orchestration** | Strong (for its scope) | Pipeline is 4 sequential pure-function steps. Each step's output is logged as structured JSON keyed by `player_id`. `processing_time_ms` tracked end-to-end. Steps are independent — one failing doesn't silently corrupt downstream. |
| **Context / Budget** | Weak | No token budgeting. RAG `top_k=3` hardcoded. No output pruning beyond system-prompt "No walls of text". Expected — this is a per-ticket system, not a long-running session. |
| **Failure / Recovery** | Strong | Explicit failure taxonomy in `qa/common-failure-patterns.md` (6 named patterns w/ example + why + correction). Evaluator distinguishes **false negative (missed escalation)** from **false positive (unnecessary escalation)** and labels false-negative "highest risk failures". This is asymmetric-cost failure scoring. |
| **Quality / Review** | Strong | Single 100-pt rubric for AI *and* human agents with same categories. **Fatal Errors** list forces auto-zero regardless of other scores. AI-CSAT-bias-analysis.md names the Simpson's-paradox-style selection bias that appears when AI takes easy tickets and human takes hard ones. |

---

## Depth-Layer Scan

| Layer | Finding |
|-------|---------|
| **调度层** | `pipeline.run(TicketContext) → PipelineResult` — synchronous, 4-step sequential pipe. No async, no queue, no DAG. Scale assumption is obvious: one ticket in, one decision out. Zendesk webhook fronting does inline triage + write-back — for real volume this would need a queue. |
| **实践层** | Classifier confidence formula worth reading: `confidence = top_intent_matches / total_matches_across_all_intents`, then `×0.85` damp if second-place > 0. It's a proxy for "how cleanly did the signal cluster on one intent", not a probability. Prioritizer uses `score = max(score, ...)` additively — rules can only escalate priority, never downgrade. Simple but makes the rule-ordering irrelevant. |
| **消费层** | `ResponseStrategy` is the contract between the decision layer and the generator: 4 fields (`tone_instruction`, `opening`, `action`, `collect[]`). The LLM doesn't receive the classification/escalation result raw — it receives the strategy. This is the seam that keeps the generator from reinventing the decision. |
| **状态层** | Fully stateless per-ticket. `contact_count`/`prior_resolution_attempted`/`is_vip` are passed in from the integration (Zendesk client fetches them). No session memory, no DB. Feedback/gap stores are JSON files — "appropriate for prototype scale" self-labelled. |
| **边界层** | Webhook verifies HMAC before anything else; fails closed (401) if signature invalid. Zendesk fetch wrapped in try/except with `zendesk_fetch_failed` log event — never leaks 500 without an audit trail. Classifier swallows no exceptions — any failure propagates and is logged with `player_id` context. `llm_client.generate_response` falls back to mock on API error with `[API ERROR - FALLBACK MOCK]` label — never silent fallback. |

---

## Path Dependency Speed-Assess

- **Locking decisions**: Chose keyword-based classifier (not embedding-based) as first-pass → locks them into brittle English-only signal dictionaries and forces the "confidence < 0.65 → human" escape hatch to carry all the non-English traffic. Chose local ChromaDB + local JSON files → locks them into single-node prototype scale.
- **Missed forks**: Could have used LLM-as-classifier from day one (their multilingual module proves they're comfortable with that pattern). They deliberately didn't — because "rules are auditable, ML is not" is the entire value proposition of the decision layer. This is a *chosen* lock-in, not an accidental one.
- **Self-reinforcement**: Every rule they add to the decision layer makes the system more auditable and harder to replace with an LLM classifier. The `ai-csat-bias-analysis.md` doc commits them even further — it makes the rule-layer an evaluation commitment, not just an implementation choice.
- **Lesson for us**: Copy the *chosen* lock-in, not the implementation. Orchestrator already has an LLM-heavy governance layer (`src/governance/`); the lesson is which decisions we should *pull back* into rules for auditability — specifically confidence-gated escalation, prohibited-action lists, and fatal-error scoring.

---

## Steal Sheet

### P0 — Must Steal (4 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **Rule-layer ↔ LLM-layer hard separation** | Decision layer produces a `ResponseStrategy` dataclass (tone/opening/action/collect). LLM sees only strategy + sysprompt + message — never the raw classification. Every *decide-what-to-do* step is a pure Python function with a deterministic test. | Partial overlap — we have `src/governance/policy/` and `src/governance/permissions.py`, but skill_routing and escalation logic live in `SOUL/public/prompts/skill_routing.md` (prompt, not rule). `methodology_router.md` is also prompt-based. | Extract skill-routing decision tree into Python rules (classify task → route). Keep prompts for *wording*, not *routing*. Add a `TaskStrategy` dataclass matching their `ResponseStrategy`. | ~4h |
| **`requires_human` OR-chain with hard-list intent overrides** | `requires_human = confidence < 0.65 OR intent ∈ auto_escalate_intents OR tone==THREATENING OR repeat_contact OR is_vip`. The `auto_escalate_intents = {BAN_APPEAL, FRAUD_REPORT, CHURN_RISK, UNKNOWN}` list says: *some task types are never handled autonomously, regardless of confidence*. | We have `src/governance/clarification.py` with confidence fields but no hard-list task types that bypass confidence. `dispatch-gate` hook blocks `[STEAL]` on wrong branches — that's a close analogue but only for one task type. | Add `src/governance/auto_escalate_tasks.py` — a YAML/Python table of task types that *always* require owner confirmation (irreversible ops, external sends, config edits). Plug into `dispatcher.py`. | ~3h |
| **Fatal Errors (auto-zero) in eval rubric** | `qa/qa-framework.md` defines 100-pt weighted rubric, then lists 5 **Fatal Errors** that force score=0 regardless of other categories: hallucinated policy / asked for password / promised outcome / disclosed 3rd-party info / failed to escalate security. Fatal errors are *physical* red lines, not score deductions. | `src/governance/eval/scoring.py` has rubric + weights (R38 AdaRubric) but no fatal-error short-circuit. A hallucinated policy can still score 70 if other categories are good. | Add `fatal_errors: list[Callable]` to `RubricCriterion` or as a separate pre-check in `score_with_rubric`. If any fatal check trips → return `ScoringResult(composite=0.0, fatal=<which>)`. | ~2h |
| **Escalation handoff separates "observed facts" from "player claims"** | System-prompt rule (enforced in handoff note format): issue type / facts provided by player (labelled `"player states..."`) / steps attempted / reason / priority / flags. "Separate observed facts from player claims. Do not present unverified player statements as confirmed facts." | `src/governance/task_handoff.py` exists but doesn't enforce epistemic labels. Subagent results come back mixed with "I found X" (observed) and "the user said Y" (claimed) without distinction, so parent agent can't weight them. | Extend handoff schema with 3 fields: `observed: list[Evidence]`, `claimed: list[Claim]`, `attempted: list[Action]`. Add a lint rule that rejects handoff text containing "user said" / "user claims" outside the `claimed` field. | ~3h |

### P1 — Worth Doing (4 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Asymmetric-cost failure metric** | Evaluator labels `false_negatives` (should-escalate-didn't) as "highest risk failures" and reports them separately from `false_positives` (unnecessary escalations). The evaluator's `passed` metric is `escalation_match` only — intent mismatch is a warning, not a failure. | Update `src/governance/eval/scoring.py` to report `ask_user_missed` vs `ask_user_unneeded` as separate buckets for confirmation decisions. Treat "didn't ask when should have" as a tier higher than "asked when didn't need to". | ~2h |
| **Gap tracker for low-confidence cases** | `feedback/gap_tracker.py` records every case where classification confidence < threshold OR intent == UNKNOWN OR RAG retrieval scores all below `MIN_RELEVANCE_SCORE`. `get_gap_summary()` groups by reason + by intent for weekly review. | Add a `src/governance/learning/gap_log.jsonl` that captures: classifier failures, skill-routing fallbacks, RAG retrieval floor misses. Surface in weekly `/status` command. This is our "what do we not yet know how to handle" corpus. | ~3h |
| **Mock-mode fallback (no-API-key deterministic responses)** | `llm_client.py` — `MOCK_MODE = not bool(ANTHROPIC_API_KEY)`. When mock, returns pre-canned per-intent response. Clearly labelled `[API ERROR - FALLBACK MOCK]` on API failure. Never silent. | Add mock mode to `src/governance/executor.py` — when `ORCHESTRATOR_MOCK=1`, return deterministic stubs per task-type. Value: CI tests that don't burn API credits; onboarding demos that work without keys. | ~2h |
| **Complexity-controlled eval comparison** | `qa/ai-csat-bias-analysis.md` — segment metrics by complexity band (Simple 5-7 / Moderate 8-11 / Complex 12-15), report each band separately, refuse to aggregate. Addresses the case where AI handles easy tickets and scores high vs human who handles hard ones and scores low. | When comparing agent configs (R38 experiment ledger), tag tasks with complexity score (`num_steps × num_files × has_external_IO`). Only compare configs within the same complexity band. Prevents self-selecting-simple-tasks bias. | ~4h |

### P2 — Reference Only (3 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **Decision-table doc format** (`knowledge-base/decision-table.md`) | 10-column table per issue type: Intent / Required Info / Allowed Actions / Prohibited / Escalate? / Trigger / Target / Priority / Notes | Great idea but already partially realized in our skill `constraints/` layer 0 and `prohibited_operations.yaml`. Worth referencing as a UX template for those docs, not copying wholesale. |
| **Prepend language instruction to sysprompt** | `multilingual/language_handler.py:36-54` — language instruction prepended (not appended) because "Claude processes top-to-bottom and language is highest-priority formatting". | Correct insight but Orchestrator already operates in Chinese-always mode via project CLAUDE.md Voice section. Keep as note for future multilingual-skill work. |
| **Markdown `##`-header RAG chunking** | `rag/kb_sync.py:chunk_markdown` — split on `## ` headers, skip <50-char sections, metadata carries `source` + `section` + `chunk_index`. | Standard LangChain/LlamaIndex pattern. Reference when we build a KB retrieval layer; not worth copying the implementation. |

---

## Comparison Matrix (P0 patterns only)

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| Decision layer is deterministic Python | `engine/classifier.py` + `engine/escalation.py`, 280 LOC of pure functions with unit tests (`tests/test_classifier.py`) | Routing in `SOUL/public/prompts/skill_routing.md` — prompt-based decision tree. `src/governance/dispatcher.py` exists but dispatches to skills/agents, doesn't classify tasks. | **Large** — we have no deterministic task classifier. | Steal — build `src/governance/task_classifier.py` + `src/governance/task_router.py` with equivalent structure. |
| Hard-list task types that always require human | `auto_escalate_intents = {BAN_APPEAL, FRAUD_REPORT, CHURN_RISK, UNKNOWN}` in `classifier.py:161` | Gate Functions in CLAUDE.md are prose ("Before any dangerous operation, walk through the gate") — agent-enforced, not code-enforced. `.claude/hooks/` has dispatch-gate for `[STEAL]` but only one task type. | **Medium** — concept exists but not generalized. | Steal — promote Gate Functions to a Python table consumed by hooks. |
| Fatal-error auto-zero in eval | `qa-framework.md` lists 5 fatal errors that zero the score. Not code yet, but committed doc. | `src/governance/eval/scoring.py` has 3-level verdicts per criterion + DimensionAwareFilter. No short-circuit for catastrophic failures. | **Medium** — rubric exists, short-circuit missing. | Steal — add `FatalCheck` pre-filter to `score_with_rubric`. |
| Epistemic labelling in handoff | System-prompt forces "player states..." prefix for unverified claims. Eval criterion scores handoff completeness. | `src/governance/task_handoff.py` — free-form note field, no schema enforcement of claimed vs observed. | **Medium** — we have handoff, missing the epistemic split. | Steal — extend `TaskHandoff` schema with three explicit lists. |

---

## Triple Validation Gate (P0 patterns)

| Pattern | Cross-domain | Generative power | Exclusivity | Score |
|---------|-------------|-----------------|-------------|-------|
| Rule-layer ↔ LLM-layer hard separation | ✅ Appears in Intercom Fin, Ada, Zendesk AI (support), LangGraph (general) | ✅ Predicts: any decision the business must audit → rule; any wording the user reads → LLM | ⚠️ Partial — "separate rules from generation" is a best-practice label, but the `ResponseStrategy` contract as the *explicit seam* is distinctive | **3/3** — the `ResponseStrategy` dataclass is the specific twist |
| `requires_human` OR-chain + hard-list | ✅ Independently in R63 Archon's safety gates and R77 Hermes's quality_gate | ✅ "What task types should never be autonomous regardless of confidence" is directly actionable for any agent framework | ✅ Most frameworks either use confidence OR hard-list; combining them with explicit OR semantics is uncommon | **3/3** |
| Fatal-error auto-zero | ✅ Airline safety rubrics, medical exam pass/fail short-circuits | ✅ Tells us: identify ≤5 catastrophic failure modes per domain, short-circuit scoring | ⚠️ Common in safety-critical domains, less common in software eval | **2/3** — caveat: downgrade if we find it's just borrowed from aviation |
| Observed vs claimed epistemic labels | ✅ Journalism (attributed vs reported), intelligence (HUMINT source grading), R42 memory evidence tiers (verbatim/artifact/impression) | ✅ Directly tells the receiving agent which inputs to trust at face value vs verify | ✅ Most handoff schemas don't separate these — they treat all context as equally reliable | **3/3** |

---

## Knowledge Irreplaceability (P0 patterns)

| Pattern | Pitfall | Heuristic | Relationship | Hidden ctx | Failure mem | Unique behavior | Total |
|---------|---------|-----------|--------------|------------|-------------|----------------|-------|
| Rule-LLM separation | ✅ "wrongly resolved > wrongly escalated" cost asymmetry | ✅ confidence < 0.65 threshold | — | ✅ "rules are auditable to non-tech stakeholders" | — | ✅ ResponseStrategy-as-seam pattern | **4/6 → P0** |
| requires_human OR-chain | ✅ LLM over-resolution anti-pattern | ✅ hard-list bypasses confidence | — | ✅ "some intents never self-resolve regardless of confidence" | ✅ "unauthorized promises" pattern from QA | — | **4/6 → P0** |
| Fatal-error auto-zero | ✅ "hallucinated policy still scoring 70" | ✅ 5 is the right number of fatal checks | — | ✅ "these are physical red lines, not preferences" | ✅ past production incidents anchor the list | — | **4/6 → P0** |
| Observed vs claimed | — | ✅ never present claim as fact | — | ✅ "trust vs verify" in handoff | ✅ `ai-csat-bias-analysis.md`: wrong decisions from treating claims as facts | ✅ explicit text prefix rule | **4/6 → P0** |

---

## Gaps Identified

Mapped to six dimensions:

| Dimension | Gap this project exposes in Orchestrator |
|-----------|----------------------------------------|
| **Security / Governance** | We don't have a *task-type* hard list that forces human approval regardless of confidence. Our Gate Functions are prose instructions; theirs is an enum literal. |
| **Memory / Learning** | No gap-tracker analogue — we don't systematically log "cases where our classifier/router failed" in one review-ready artifact. Our memory captures what we did; theirs also captures what we couldn't do. |
| **Execution / Orchestration** | Our task routing is prompt-driven (`methodology_router.md` + `skill_routing.md`). Pipeline-as-pure-functions is not our pattern. Trade-off: ours adapts; theirs audits. |
| **Context / Budget** | N/A — not a concern at their scale. Both projects lack per-field token budgeting for now. |
| **Failure / Recovery** | We lack an asymmetric-cost failure metric. When an agent fails to ask the user for confirmation on a dangerous op, we count it the same as a noisy unnecessary confirmation — they are *not* the same cost. |
| **Quality / Review** | `src/governance/eval/scoring.py` has weighted rubric but no fatal-error short-circuit. A hallucinated hard-constraint response can score well on other dims and obscure the actual failure. |

---

## Adjacent Discoveries

- **`all-MiniLM-L6-v2` as local embedding model** — 80MB, runs on CPU, real-time latency. Worth remembering next time we need embeddings without a hosted service. No stealing needed, just note.
- **Section-chunk markdown for RAG** — `rag/kb_sync.py:chunk_markdown` is 30 lines. If we ever need KB-from-docs retrieval, this is a concrete starting point smaller than reaching for LangChain.
- **Synthetic ticket generator as eval input** — `evaluation/scripts/fetch_tickets.py` generates realistic-but-fictional tickets. Same pattern would apply to generating synthetic "agent tasks" for eval regression testing.
- **Tone-guide "banned phrases" table** — `tone-guide.md:63-74` lists specific phrases to avoid and their replacements. We maintain voice rules in prose in boot.md/voice.md. A banned-phrase table would be a stronger physical artifact — and testable by grep.

---

## Meta Insights

1. **Rules are what auditors read; prompts are what models read.** The author's key commitment is that *everything a non-technical stakeholder needs to understand* (routing, priority, escalation, what the agent is forbidden to promise) is a rules table, not a prompt instruction. Orchestrator leans the other way — governance-by-prompt — because we prioritize adaptability. The steal is not "convert everything to rules" but "identify the specific decisions where auditability matters more than adaptability, and pull those decisions into Python." Confidence-gated escalation, prohibited-action lists, and fatal-error scoring are the candidates.

2. **The LLM's structural bug is sycophancy, not hallucination.** `prompt-engineering-notes.md:44` explicitly names "unauthorized promises" as the worst failure mode — not because the LLM gets facts wrong, but because it will cheerfully *reduce friction* by promising what it shouldn't. Hallucination is downstream of this. The physical fix is forcing the LLM's output to pass through a rule-checked `ResponseStrategy`, so even if it wants to promise a refund, the `action` field doesn't contain that option.

3. **False negative ≫ false positive when the wrong answer has real-world cost.** Their evaluator makes this concrete: `passed = escalation_match` only. Intent mismatch is a warning. Missed escalation is a failure. We have a similar asymmetry everywhere: *failing to ask for confirmation on a dangerous op* ≫ *asking unnecessarily*, *missing a git rollback backup* ≫ *making an unneeded backup*. Our metrics should reflect this asymmetry; right now they don't.

4. **Selection bias in self-improving agents.** `ai-csat-bias-analysis.md` names a specific Simpson's-paradox-style trap: if AI handles easy tickets and human handles hard ones, CSAT comparisons favor AI even when AI is the weaker agent. This applies directly to R38's auto-agent evaluation ledger — if an agent can *select* which tasks feed its own eval, it will drift toward the easy ones and report improving scores on flat or declining capability. The mitigation is complexity-band-segmented eval, which we currently don't implement.

5. **The skeleton-vs-framework tradeoff.** This project has 0 stars and is 2 days old; most of it isn't wired to live traffic (`LIMITATIONS.md` is brutally honest about this). But the *decisions it has already made* — where the rule/LLM boundary lives, what's in the fatal-error list, what the asymmetric-cost failure mode is — are exactly the decisions that expensive frameworks dodge by being configurable. A skeleton that commits to opinions beats a framework that lets you configure yourself into the wrong answer. Orchestrator has the same problem pending: many of our `SOUL/public/prompts/` files are configurable-by-prompt when they should be opinionated-by-code.
