"""Elder Council — 中书省五元老审议系统。

Stolen from: karpathy/llm-council (Round 19).
Core patterns:
  1. Anonymized peer review — elders see "Opinion A/B/C", not who said it
  2. Ranking aggregation — richer signal than binary agree/disagree
  3. Chairman as synthesizer — receives all opinions + rankings, makes final call
  4. Structured output with fallback parsing — graceful degradation

Key difference from llm-council: our elders are NOT different models.
They are different *deliberation lenses* (personas) that can run on
the same model. This is cheaper and more controllable — the diversity
comes from perspective, not from model architecture.

Usage:
    council = ElderCouncil()
    verdict = council.deliberate(
        question="Should we refactor the auth module?",
        context="Current auth uses session tokens...",
    )
    print(verdict.decision)       # "approve" / "reject" / "defer"
    print(verdict.ranking)        # [("advocate", 1.2), ("architect", 2.0), ...]
    print(verdict.synthesis)      # Chairman's synthesis
"""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from src.governance.safety.injection_scanner import scan_agent_output, has_high_severity

log = logging.getLogger(__name__)


# ── Elder Definitions ──────────────────────────────────────────

@dataclass(frozen=True)
class Elder:
    """One member of the council — a deliberation lens, not a model."""
    key: str            # internal ID
    title: str          # display name (中文)
    perspective: str    # one-line description of what they focus on
    prompt_prefix: str  # injected into their deliberation prompt

ELDERS: dict[str, Elder] = {
    "conservative": Elder(
        key="conservative",
        title="稳健公",
        perspective="风险与爆炸半径",
        prompt_prefix=(
            "You are the Conservative Elder. Your role is to identify risks, "
            "blast radius, and rollback difficulty. You are naturally skeptical "
            "of changes that touch shared infrastructure, schemas, or external APIs. "
            "Ask: 'What happens if this goes wrong? Can we undo it?'"
        ),
    ),
    "pragmatist": Elder(
        key="pragmatist",
        title="务实公",
        perspective="交付效率与最短路径",
        prompt_prefix=(
            "You are the Pragmatist Elder. Your role is to evaluate execution "
            "efficiency. You favor the simplest approach that solves the problem. "
            "You push back on over-engineering, unnecessary abstractions, and "
            "tasks that could be done in 1 step but are planned as 5. "
            "Ask: 'Is this the shortest path to done?'"
        ),
    ),
    "architect": Elder(
        key="architect",
        title="匠心公",
        perspective="长期架构与技术债",
        prompt_prefix=(
            "You are the Architect Elder. Your role is to evaluate long-term "
            "architectural impact. You care about maintainability, patterns, "
            "and whether this decision creates tech debt. You think in terms "
            "of 6 months from now. Ask: 'Will we regret this in half a year?'"
        ),
    ),
    "guardian": Elder(
        key="guardian",
        title="铁卫公",
        perspective="安全与合规",
        prompt_prefix=(
            "You are the Guardian Elder. Your role is to evaluate security "
            "posture, data safety, and compliance. You look for injection "
            "vectors, credential exposure, and permission escalation. "
            "Ask: 'What is the attack surface here?'"
        ),
    ),
    "advocate": Elder(
        key="advocate",
        title="民意公",
        perspective="用户价值与实际需求",
        prompt_prefix=(
            "You are the Advocate Elder. Your role is to represent the user's "
            "interests. You evaluate whether the proposed action actually solves "
            "the user's problem, whether the output is useful, and whether "
            "effort is proportional to value. Ask: 'Does the boss actually need this?'"
        ),
    ),
}

# Who synthesizes. Not a council member — receives all data and decides.
CHAIRMAN_PROMPT_PREFIX = (
    "You are the Chairman of the Elder Council (中书省). You have received "
    "deliberation opinions from five elders, each with a different perspective, "
    "plus their peer rankings of each other's opinions. Your job is to synthesize "
    "all of this into a single, clear decision. You are not a voter — you are "
    "a judge who weighs all evidence and makes the final call.\n\n"
    "ANTI-SYCOPHANCY PROTOCOL: Never use phrases like 'Great point', "
    "'You're absolutely right', or 'Thanks for catching that'. Your synthesis "
    "must contain only technical statements. If an elder's opinion is wrong, "
    "say so with evidence — disagreement is not disrespect."
)


# ── Result Types ───────────────────────────────────────────────

@dataclass
class ElderOpinion:
    """One elder's deliberation output."""
    elder_key: str
    label: str          # anonymized label ("Opinion A", etc.)
    text: str           # full response
    stance: str         # "approve" / "reject" / "caution" (parsed)
    confidence: float   # 0.0-1.0 (parsed)
    severity: str = "medium"  # "high" / "medium" / "low" (Round 22: Review Swarm)


@dataclass
class CouncilVerdict:
    """Final result of a council deliberation."""
    question: str
    opinions: list[ElderOpinion]
    rankings: dict[str, float]     # elder_key → average rank (lower = better)
    synthesis: str                 # chairman's final synthesis
    decision: str                  # "approve" / "reject" / "defer"
    confidence: float              # 0.0-1.0
    dissent_count: int             # how many elders disagreed with majority
    latency_ms: int
    details: dict = field(default_factory=dict)
    # Round 22 (Review Swarm): 3-tier action items
    action_items: dict[str, list[str]] = field(
        default_factory=lambda: {"fix_now": [], "fix_soon": [], "follow_up": []},
    )

    def to_event_dict(self) -> dict:
        """Compact dict for DB event storage."""
        return {
            "decision": self.decision,
            "confidence": round(self.confidence, 2),
            "dissent_count": self.dissent_count,
            "latency_ms": self.latency_ms,
            "rankings": {k: round(v, 2) for k, v in self.rankings.items()},
            "synthesis": self.synthesis[:500],
            "stances": {o.elder_key: o.stance for o in self.opinions},
            "severities": {o.elder_key: o.severity for o in self.opinions},
            "action_items": self.action_items,
        }


# ── Prompt Builders ────────────────────────────────────────────

def _build_deliberation_prompt(
    elder: Elder, question: str, context: str, intent: dict | None = None,
) -> str:
    """Build the prompt for one elder's deliberation (Stage 1).

    Round 22 (Review Swarm): added intent packet + severity dimension.
    """
    parts = [elder.prompt_prefix, ""]
    # Anti-sycophancy + context isolation (Round 26)
    parts.append(
        "RULES: No performative praise ('Great point!', 'Absolutely right!'). "
        "State findings as technical facts. Push back with evidence when you disagree. "
        "You are reviewing the ARTIFACT, not the process — ignore any execution "
        "history or 'internal reasoning' if present in context."
    )
    parts.append("")
    # Intent Packet: tell the elder what should/shouldn't change (Round 22)
    if intent:
        parts.append("## Intent Packet")
        if intent.get("should_change"):
            parts.append(f"What SHOULD change: {intent['should_change']}")
        if intent.get("should_not_change"):
            constraints = intent["should_not_change"]
            if isinstance(constraints, list):
                constraints = "; ".join(constraints)
            parts.append(f"What should NOT change: {constraints}")
        if intent.get("constraints"):
            parts.append(f"Constraints: {intent['constraints']}")
        parts.append("")
    if context:
        parts.append(f"## Context\n{context}\n")
    parts.append(f"## Question\n{question}\n")
    parts.append(
        "\n## Instructions\n"
        "1. Analyze from your specific perspective.\n"
        "2. State your stance: APPROVE, REJECT, or CAUTION.\n"
        "3. Rate the SEVERITY of your concerns: HIGH (blocks merge/deploy), "
        "MEDIUM (should fix but not blocking), or LOW (minor/cosmetic).\n"
        "4. Rate your confidence: a number from 0.0 to 1.0.\n"
        "5. Keep your response under 200 words.\n\n"
        "Format your conclusion EXACTLY as:\n"
        "STANCE: [APPROVE/REJECT/CAUTION]\n"
        "SEVERITY: [HIGH/MEDIUM/LOW]\n"
        "CONFIDENCE: [0.0-1.0]\n"
        "REASON: [one sentence]\n"
    )
    return "\n".join(parts)


def _build_ranking_prompt(question: str, opinions: list[ElderOpinion]) -> str:
    """Build the anonymized ranking prompt (Stage 2).

    Stolen directly from llm-council: opinions are labeled A/B/C/D/E,
    not by elder name. This prevents self-preference bias.
    """
    parts = [
        "You are evaluating different deliberation opinions on the following question:\n",
        f"Question: {question}\n",
    ]
    for op in opinions:
        parts.append(f"--- {op.label} ---\n{op.text[:600]}\n")

    parts.append(
        "\n## Instructions\n"
        "1. Briefly evaluate each opinion (1 sentence each).\n"
        "2. Rank ALL opinions from best to worst.\n\n"
        "IMPORTANT: End with EXACTLY this format:\n"
        "FINAL RANKING:\n"
        "1. Opinion X\n"
        "2. Opinion Y\n"
        "3. Opinion Z\n"
        "... (list all opinions)\n"
    )
    return "\n".join(parts)


def _build_chairman_prompt(
    question: str,
    context: str,
    opinions: list[ElderOpinion],
    rankings: dict[str, float],
    label_to_elder: dict[str, str],
) -> str:
    """Build the chairman synthesis prompt (Stage 3).

    Chairman sees everything: real elder names, full opinions, aggregated rankings.
    Unlike the ranking stage, no anonymization here — the chairman needs full context.
    """
    parts = [CHAIRMAN_PROMPT_PREFIX, ""]
    if context:
        parts.append(f"## Context\n{context}\n")
    parts.append(f"## Question\n{question}\n")

    parts.append("## Elder Opinions\n")
    for op in opinions:
        elder = ELDERS.get(op.elder_key)
        title = elder.title if elder else op.elder_key
        parts.append(f"### {title} ({elder.perspective if elder else ''})")
        parts.append(f"Stance: {op.stance.upper()} | Severity: {op.severity.upper()} | Confidence: {op.confidence}")
        parts.append(f"{op.text[:800]}\n")

    parts.append("## Peer Ranking (average position, lower = better)\n")
    sorted_ranks = sorted(rankings.items(), key=lambda x: x[1])
    for elder_key, avg_rank in sorted_ranks:
        elder = ELDERS.get(elder_key)
        title = elder.title if elder else elder_key
        parts.append(f"- {title}: {avg_rank:.1f}")

    # Round 22 (Review Swarm): explicit filtering protocol + 3-tier output
    parts.append(
        "\n## Filtering Protocol (apply before synthesizing)\n"
        "1. Drop opinions that merely restate another elder's point.\n"
        "2. Drop speculative concerns without concrete evidence.\n"
        "3. Drop concerns that conflict with the stated intent (if provided).\n"
        "4. Drop minor style/cosmetic issues unless they hide a real bug.\n"
        "5. Normalize surviving concerns by severity (HIGH > MEDIUM > LOW).\n"
    )
    parts.append(
        "\n## Your Task\n"
        "Synthesize all opinions and rankings into a final decision.\n"
        "Consider: agreement patterns, the strength of dissenting views, "
        "and whether high-ranked opinions align with each other.\n\n"
        "After the decision, provide a PATH FORWARD with three tiers:\n"
        "FIX_NOW: [issues that must be resolved before merge/deploy]\n"
        "FIX_SOON: [issues worth fixing if time permits]\n"
        "FOLLOW_UP: [minor items that can be tracked separately]\n"
        "Use 'none' if a tier is empty.\n\n"
        "End with EXACTLY:\n"
        "DECISION: [APPROVE/REJECT/DEFER]\n"
        "CONFIDENCE: [0.0-1.0]\n"
        "REASON: [2-3 sentences]\n"
        "FIX_NOW: [comma-separated items or 'none']\n"
        "FIX_SOON: [comma-separated items or 'none']\n"
        "FOLLOW_UP: [comma-separated items or 'none']\n"
    )
    return "\n".join(parts)


# ── Parsing ────────────────────────────────────────────────────

def _parse_stance(text: str) -> tuple[str, float, str]:
    """Parse STANCE, CONFIDENCE, and SEVERITY from elder output.

    Round 22 (Review Swarm): added severity parsing.
    """
    stance = "caution"  # default
    confidence = 0.5
    severity = "medium"  # default

    for line in text.splitlines():
        line_upper = line.strip().upper()
        if line_upper.startswith("STANCE:"):
            val = line_upper.replace("STANCE:", "").strip()
            if "APPROVE" in val:
                stance = "approve"
            elif "REJECT" in val:
                stance = "reject"
            else:
                stance = "caution"
        elif line_upper.startswith("CONFIDENCE:"):
            try:
                confidence = float(re.search(r'[\d.]+', line).group())
                confidence = max(0.0, min(1.0, confidence))
            except (AttributeError, ValueError):
                pass
        elif line_upper.startswith("SEVERITY:"):
            val = line_upper.replace("SEVERITY:", "").strip()
            if "HIGH" in val:
                severity = "high"
            elif "LOW" in val:
                severity = "low"
            else:
                severity = "medium"

    return stance, confidence, severity


def _parse_ranking(text: str, num_opinions: int) -> list[str]:
    """Parse FINAL RANKING from ranking output. Two-level fallback (llm-council pattern).

    Returns list of labels like ["Opinion C", "Opinion A", "Opinion B", ...]
    """
    # Level 1: strict format after "FINAL RANKING:"
    if "FINAL RANKING:" in text.upper():
        section = text.upper().split("FINAL RANKING:")[-1]
        matches = re.findall(r'\d+\.\s*OPINION\s+([A-Z])', section)
        if len(matches) >= num_opinions - 1:  # allow one missing
            return [f"Opinion {m}" for m in matches]

    # Level 2: fallback — scan entire text for "Opinion X" tokens
    all_mentions = re.findall(r'Opinion\s+([A-Z])', text, re.IGNORECASE)
    # Deduplicate preserving order
    seen = set()
    unique = []
    for m in all_mentions:
        m_upper = m.upper()
        if m_upper not in seen:
            seen.add(m_upper)
            unique.append(f"Opinion {m_upper}")
    return unique


def _parse_decision(text: str) -> tuple[str, float, dict[str, list[str]]]:
    """Parse DECISION, CONFIDENCE, and action items from chairman output.

    Round 22 (Review Swarm): added 3-tier action items parsing.
    """
    decision = "defer"
    confidence = 0.5
    action_items: dict[str, list[str]] = {"fix_now": [], "fix_soon": [], "follow_up": []}

    tier_map = {"FIX_NOW": "fix_now", "FIX_SOON": "fix_soon", "FOLLOW_UP": "follow_up"}

    for line in text.splitlines():
        line_upper = line.strip().upper()
        if line_upper.startswith("DECISION:"):
            val = line_upper.replace("DECISION:", "").strip()
            if "APPROVE" in val:
                decision = "approve"
            elif "REJECT" in val:
                decision = "reject"
            else:
                decision = "defer"
        elif line_upper.startswith("CONFIDENCE:"):
            try:
                confidence = float(re.search(r'[\d.]+', line).group())
                confidence = max(0.0, min(1.0, confidence))
            except (AttributeError, ValueError):
                pass
        else:
            # Parse FIX_NOW / FIX_SOON / FOLLOW_UP lines
            for prefix, key in tier_map.items():
                if line_upper.startswith(f"{prefix}:"):
                    raw = line.strip()[len(prefix) + 1:].strip()
                    if raw.lower() not in ("none", "n/a", ""):
                        items = [i.strip() for i in raw.split(",") if i.strip()]
                        action_items[key].extend(items)

    return decision, confidence, action_items


# ── Ranking Aggregation ────────────────────────────────────────

def aggregate_rankings(
    all_rankings: list[list[str]],
    label_to_elder: dict[str, str],
) -> dict[str, float]:
    """Aggregate multiple ranking lists into average positions.

    Stolen from llm-council: each ranker assigns positions (1=best),
    we average across all rankers. Lower average = better opinion.
    """
    positions: dict[str, list[int]] = {ek: [] for ek in label_to_elder.values()}

    for ranking in all_rankings:
        for position, label in enumerate(ranking, start=1):
            elder_key = label_to_elder.get(label)
            if elder_key and elder_key in positions:
                positions[elder_key].append(position)

    # Calculate average rank; missing = worst rank (len(ELDERS) + 1)
    num_elders = len(label_to_elder)
    avg_ranks: dict[str, float] = {}
    for elder_key, pos_list in positions.items():
        if pos_list:
            avg_ranks[elder_key] = sum(pos_list) / len(pos_list)
        else:
            avg_ranks[elder_key] = num_elders + 1  # penalty for unranked

    return avg_ranks


# ── The Council ────────────────────────────────────────────────

class ElderCouncil:
    """Five-elder deliberation council for the 中书省.

    Three-stage pipeline:
      Stage 1: All elders deliberate independently (parallel)
      Stage 2: Each elder ranks all opinions anonymously (parallel)
      Stage 3: Chairman synthesizes everything into a final verdict

    Uses a single model (configurable) — diversity comes from personas,
    not model architecture. This is intentional: same reasoning engine,
    different lenses, produces more controllable disagreement than
    random model-to-model variance.
    """

    def __init__(
        self,
        model: str | None = None,
        chairman_model: str | None = None,
        elders: dict[str, Elder] | None = None,
        max_tokens: int = 512,
        skip_ranking: bool = False,
    ):
        from src.core.llm_models import MODEL_HAIKU, MODEL_SONNET
        self.model = model or MODEL_HAIKU          # elders use cheaper model
        self.chairman_model = chairman_model or MODEL_SONNET  # chairman uses stronger
        self.elders = elders or ELDERS
        self.max_tokens = max_tokens
        self.skip_ranking = skip_ranking  # skip Stage 2 for speed (light mode)

    def deliberate(
        self,
        question: str,
        context: str = "",
        timeout: float = 120.0,
        intent: dict | None = None,
    ) -> CouncilVerdict:
        """Run the full three-stage deliberation pipeline.

        Round 22 (Review Swarm): added intent parameter for Intent Packet.
        """
        t0 = time.time()

        # ── Stage 1: Independent deliberation (parallel) ──
        opinions, label_to_elder = self._stage1_deliberate(
            question, context, timeout, intent=intent,
        )

        if len(opinions) < 2:
            # Not enough opinions to deliberate — fallback to single opinion
            return self._fallback_verdict(question, opinions, t0)

        # ── Stage 2: Anonymized peer ranking (parallel, optional) ──
        if self.skip_ranking:
            # Light mode: derive rankings from stance/confidence only
            rankings = self._rankings_from_stances(opinions)
        else:
            rankings = self._stage2_rank(question, opinions, label_to_elder, timeout)

        # ── Shared Board (R74 ChatDev): opinions as blackboard for chairman ──
        from src.governance.context.blackboard import create_reflexion_blackboard
        bb = create_reflexion_blackboard()
        for op in opinions:
            bb.write(
                "reflection_writer",
                f"[{op.stance} conf={op.confidence:.2f}] {op.text[:300]}",
                metadata={"elder": op.elder_key, "label": op.label},
            )
        board_text = bb.format_for_prompt("synthesizer", top_k=len(opinions))
        synth_context = context + ("\n\n" + board_text if board_text else "")

        # ── Stage 3: Chairman synthesis ──
        synthesis, decision, confidence, action_items = self._stage3_synthesize(
            question, synth_context, opinions, rankings, label_to_elder, timeout,
        )

        # Count dissent
        majority_stance = decision if decision in ("approve", "reject") else "caution"
        dissent_count = sum(1 for o in opinions if o.stance != majority_stance)

        elapsed_ms = int((time.time() - t0) * 1000)

        verdict = CouncilVerdict(
            question=question,
            opinions=opinions,
            rankings=rankings,
            synthesis=synthesis,
            decision=decision,
            confidence=confidence,
            dissent_count=dissent_count,
            latency_ms=elapsed_ms,
            action_items=action_items,
        )

        log.info(
            f"council: decision={decision} confidence={confidence:.0%} "
            f"dissent={dissent_count}/5 action_items="
            f"{sum(len(v) for v in action_items.values())} ({elapsed_ms}ms)"
        )
        return verdict

    # ── Stage 1: Deliberation ──────────────────────────────────

    def _stage1_deliberate(
        self, question: str, context: str, timeout: float,
        intent: dict | None = None,
    ) -> tuple[list[ElderOpinion], dict[str, str]]:
        """All elders deliberate independently in parallel."""
        from src.core.llm_backends import claude_generate

        # Assign anonymous labels (A, B, C, D, E)
        elder_keys = list(self.elders.keys())
        labels = [f"Opinion {chr(65 + i)}" for i in range(len(elder_keys))]
        label_to_elder = dict(zip(labels, elder_keys))

        def _call_elder(elder_key: str, label: str) -> ElderOpinion:
            elder = self.elders[elder_key]
            prompt = _build_deliberation_prompt(elder, question, context, intent=intent)
            try:
                text = claude_generate(
                    prompt, self.model,
                    timeout=int(timeout / 2),
                    max_tokens=self.max_tokens,
                )
                # Round 21 (hermes-agent): scan elder output for poisoned content
                threats = scan_agent_output(f"elder-{elder_key}", text)
                if has_high_severity(threats):
                    log.warning("council: elder %s output flagged: %s", elder_key, threats[0].pattern_name)
                    return ElderOpinion(
                        elder_key=elder_key, label=label,
                        text=f"[Output blocked: {threats[0].pattern_name}]",
                        stance="caution", confidence=0.0,
                    )
                stance, confidence, severity = _parse_stance(text)
                return ElderOpinion(
                    elder_key=elder_key, label=label,
                    text=text, stance=stance, confidence=confidence,
                    severity=severity,
                )
            except Exception as e:
                log.warning(f"council: elder {elder_key} failed: {e}")
                return ElderOpinion(
                    elder_key=elder_key, label=label,
                    text=f"[Elder error: {e}]",
                    stance="caution", confidence=0.0,
                )

        opinions: list[ElderOpinion] = []
        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="council-s1") as pool:
            futures = {
                pool.submit(_call_elder, ek, lb): ek
                for ek, lb in zip(elder_keys, labels)
            }
            for future in futures:
                opinions.append(future.result(timeout=timeout))

        # Sort by label to maintain consistent order
        opinions.sort(key=lambda o: o.label)
        return opinions, label_to_elder

    # ── Stage 2: Ranking ───────────────────────────────────────

    def _stage2_rank(
        self,
        question: str,
        opinions: list[ElderOpinion],
        label_to_elder: dict[str, str],
        timeout: float,
    ) -> dict[str, float]:
        """Each elder ranks all opinions anonymously in parallel."""
        from src.core.llm_backends import claude_generate

        ranking_prompt = _build_ranking_prompt(question, opinions)
        all_rankings: list[list[str]] = []

        def _call_ranker(elder_key: str) -> list[str]:
            elder = self.elders[elder_key]
            # Prepend elder's perspective to ranking prompt
            full_prompt = f"{elder.prompt_prefix}\n\n{ranking_prompt}"
            try:
                text = claude_generate(
                    full_prompt, self.model,
                    timeout=int(timeout / 2),
                    max_tokens=self.max_tokens,
                )
                return _parse_ranking(text, len(opinions))
            except Exception as e:
                log.warning(f"council: ranker {elder_key} failed: {e}")
                return []

        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="council-s2") as pool:
            futures = [
                pool.submit(_call_ranker, ek)
                for ek in self.elders.keys()
            ]
            for future in futures:
                try:
                    ranking = future.result(timeout=timeout)
                    if ranking:
                        all_rankings.append(ranking)
                except Exception:
                    pass

        if not all_rankings:
            return self._rankings_from_stances(opinions)

        return aggregate_rankings(all_rankings, label_to_elder)

    # ── Stage 3: Chairman Synthesis ────────────────────────────

    def _stage3_synthesize(
        self,
        question: str,
        context: str,
        opinions: list[ElderOpinion],
        rankings: dict[str, float],
        label_to_elder: dict[str, str],
        timeout: float,
    ) -> tuple[str, str, float, dict[str, list[str]]]:
        """Chairman synthesizes all opinions + rankings into final decision.

        Round 22 (Review Swarm): returns action_items as 4th element.
        """
        from src.core.llm_backends import claude_generate

        prompt = _build_chairman_prompt(
            question, context, opinions, rankings, label_to_elder,
        )

        try:
            text = claude_generate(
                prompt, self.chairman_model,
                timeout=int(timeout),
                max_tokens=self.max_tokens * 2,
            )
            # Round 21 (hermes-agent): scan chairman output for poisoned content
            threats = scan_agent_output("chairman", text)
            if has_high_severity(threats):
                log.warning("council: chairman output flagged: %s", threats[0].pattern_name)
                synthesis, decision, confidence = self._majority_fallback(opinions)
                return synthesis, decision, confidence, {"fix_now": [], "fix_soon": [], "follow_up": []}
            decision, confidence, action_items = _parse_decision(text)
            return text, decision, confidence, action_items
        except Exception as e:
            log.warning(f"council: chairman synthesis failed: {e}")
            # Fallback: majority vote from elders
            synthesis, decision, confidence = self._majority_fallback(opinions)
            return synthesis, decision, confidence, {"fix_now": [], "fix_soon": [], "follow_up": []}

    # ── Fallbacks ──────────────────────────────────────────────

    def _rankings_from_stances(self, opinions: list[ElderOpinion]) -> dict[str, float]:
        """Derive pseudo-rankings from stance + confidence when Stage 2 is skipped."""
        stance_score = {"approve": 1, "caution": 2, "reject": 3}
        scored = [
            (o.elder_key, stance_score.get(o.stance, 2) - o.confidence)
            for o in opinions
        ]
        scored.sort(key=lambda x: x[1])
        return {ek: float(rank) for rank, (ek, _) in enumerate(scored, start=1)}

    def _majority_fallback(
        self, opinions: list[ElderOpinion],
    ) -> tuple[str, str, float]:
        """When chairman fails, use majority vote."""
        stance_counts: dict[str, int] = {}
        for o in opinions:
            stance_counts[o.stance] = stance_counts.get(o.stance, 0) + 1

        majority = max(stance_counts, key=stance_counts.get)
        total = len(opinions)
        confidence = stance_counts[majority] / total

        synthesis = (
            f"Chairman fallback: {stance_counts[majority]}/{total} elders voted {majority}. "
            f"Stances: {', '.join(f'{o.elder_key}={o.stance}' for o in opinions)}"
        )
        return synthesis, majority, confidence

    def _fallback_verdict(
        self, question: str, opinions: list[ElderOpinion], t0: float,
    ) -> CouncilVerdict:
        """When too few elders responded, produce a degraded verdict."""
        elapsed_ms = int((time.time() - t0) * 1000)
        if opinions:
            op = opinions[0]
            return CouncilVerdict(
                question=question, opinions=opinions,
                rankings={op.elder_key: 1.0},
                synthesis=f"Only {len(opinions)} elder(s) responded. Using single opinion.",
                decision=op.stance if op.stance in ("approve", "reject") else "defer",
                confidence=op.confidence * 0.5,  # penalize for lack of deliberation
                dissent_count=0, latency_ms=elapsed_ms,
            )
        return CouncilVerdict(
            question=question, opinions=[], rankings={},
            synthesis="No elders responded. Defaulting to defer.",
            decision="defer", confidence=0.0,
            dissent_count=0, latency_ms=elapsed_ms,
        )
