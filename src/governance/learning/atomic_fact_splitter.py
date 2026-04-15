"""Atomic Fact Splitter — decompose multi-fact memory into single-assertion atoms.

Source: R65 Headroom (headroom/memory/extraction.py)

Problem: Traditional memory stores multi-fact statements as one unit
(e.g., "Alice likes Python and lives in Beijing"). The embedding vector
is the mean of two semantic directions → degraded retrieval.

Solution: Each discrete fact is stored as a completely independent entry
with its own embedding/search surface.

Quality rules (from Headroom's get_conversation_extraction_prompt):
- Attribution: each fact must include WHO (no "user" or "I" — use real names)
- Atomicity: single assertion per fact
- Temporal resolution: relative dates → absolute ("last year" → "2023")
- Self-contained: each fact readable without context
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# ── Sentence boundary punctuation ────────────────────────────────────────

_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

# Conjunctions that signal a compound sentence (new assertion)
_COMPOUND_SPLITTERS = re.compile(
    r'\s+(?:and|also|additionally|furthermore|moreover|plus|as well as|,\s*and)\s+',
    re.IGNORECASE,
)

# Relative temporal expressions → need resolution flag
_RELATIVE_TEMPORAL = re.compile(
    r'\b(last\s+(?:year|month|week|monday|tuesday|wednesday|thursday|friday)|'
    r'yesterday|recently|a\s+while\s+ago|the\s+other\s+day|'
    r'去年|上个?月|上周|前几天|最近|不久前)\b',
    re.IGNORECASE,
)

# Vague pronouns that break self-containedness
_VAGUE_PRONOUNS = re.compile(
    r'\b(he|she|they|it|this|that|the\s+(?:user|person|individual))\b',
    re.IGNORECASE,
)


# ── Data model ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AtomicFact:
    """A single self-contained fact extracted from a memory entry."""
    content: str
    source_entry: str
    fact_index: int
    entities: list[str] = field(default_factory=list)
    confidence: float = 1.0
    temporal_refs: list[str] = field(default_factory=list)

    def __hash__(self) -> int:
        return hash(self.content)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AtomicFact):
            return self.content == other.content
        return NotImplemented


# ── Prompt builder ───────────────────────────────────────────────────────

class FactExtractionPrompt:
    """Build the LLM prompt for atomic fact extraction."""

    _SYSTEM = (
        "You are a memory distiller. Your job is to break a conversation or text "
        "into atomic facts — one assertion per fact. Each fact must be:\n"
        "1. Self-contained (readable without any surrounding context)\n"
        "2. Attributed (WHO did/said/prefers what — use real names, never 'user' or 'I')\n"
        "3. Atomic (a single assertion, not two joined by 'and')\n"
        "4. Temporally resolved (replace 'last year' with the actual year)\n\n"
        "Return JSON: {\"facts\": [\"fact1\", \"fact2\", ...]}\n"
        "Return an empty list if no facts can be extracted."
    )

    _FEW_SHOT = [
        {
            "role": "user",
            "content": (
                "Extract atomic facts from:\n"
                "\"John likes Python and moved to Berlin last year.\""
            ),
        },
        {
            "role": "assistant",
            "content": json.dumps({
                "facts": [
                    "John likes Python.",
                    "John moved to Berlin in 2024.",
                ]
            }),
        },
        {
            "role": "user",
            "content": (
                "Extract atomic facts from:\n"
                "\"She recently finished reading Clean Code and found it useful.\""
            ),
        },
        {
            "role": "assistant",
            "content": json.dumps({
                "facts": []
            }),
            # Bad example: vague "she", unresolved "recently" — should yield empty
        },
        # Good rewrite of the above (to show the contrast):
        {
            "role": "user",
            "content": (
                "Extract atomic facts from:\n"
                "\"Maria finished reading Clean Code in March 2024 and found it useful.\""
            ),
        },
        {
            "role": "assistant",
            "content": json.dumps({
                "facts": [
                    "Maria finished reading 'Clean Code' in March 2024.",
                    "Maria found 'Clean Code' useful.",
                ]
            }),
        },
    ]

    @classmethod
    def build_prompt(
        cls,
        conversation_text: str,
        user_name: str | None = None,
    ) -> list[dict[str, str]]:
        """Build a messages list suitable for an OpenAI-compatible LLM call.

        Args:
            conversation_text: The text to decompose into atomic facts.
            user_name: Optional real name for the primary subject; if provided,
                       instructs the LLM to use it instead of 'user' or 'I'.

        Returns:
            List of message dicts: [{"role": ..., "content": ...}, ...]
        """
        system = cls._SYSTEM
        if user_name:
            system = system.replace(
                "use real names, never 'user' or 'I'",
                f"use real names — the primary user is '{user_name}'",
            )

        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(cls._FEW_SHOT)
        messages.append({
            "role": "user",
            "content": f"Extract atomic facts from:\n\"{conversation_text}\"",
        })
        return messages


# ── LLM response parser ──────────────────────────────────────────────────

def parse_facts_response(llm_response: str) -> list[AtomicFact]:
    """Parse the LLM JSON response into AtomicFact objects.

    Handles:
    - Bare JSON object: {"facts": [...]}
    - JSON wrapped in markdown fences: ```json ... ```
    - Partial extraction if outer structure is malformed

    Args:
        llm_response: Raw string from the LLM.

    Returns:
        List of AtomicFact objects. Empty list on parse failure.
    """
    text = llm_response.strip()

    # Strip markdown fences if present
    fence_match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract just the facts array
        arr_match = re.search(r'"facts"\s*:\s*(\[[\s\S]+?\])', text)
        if not arr_match:
            log.warning("parse_facts_response: no valid JSON found in response")
            return []
        try:
            data = {"facts": json.loads(arr_match.group(1))}
        except json.JSONDecodeError:
            log.warning("parse_facts_response: could not parse facts array")
            return []

    raw_facts: list[str] = []
    if isinstance(data, dict):
        raw_facts = data.get("facts", [])
    elif isinstance(data, list):
        raw_facts = data

    result: list[AtomicFact] = []
    for idx, item in enumerate(raw_facts):
        if not isinstance(item, str) or not item.strip():
            continue
        content = item.strip()
        valid, _ = validate_fact(content)
        confidence = 1.0 if valid else 0.5
        temporal_refs = _RELATIVE_TEMPORAL.findall(content)
        entities = _extract_entities(content)
        result.append(AtomicFact(
            content=content,
            source_entry=llm_response[:80],
            fact_index=idx,
            entities=entities,
            confidence=confidence,
            temporal_refs=[t if isinstance(t, str) else t[0] for t in temporal_refs],
        ))

    return result


# ── Rule-based splitter (LLM fallback) ──────────────────────────────────

def split_into_atomic_facts(text: str) -> list[str]:
    """Rule-based decomposition of text into single-assertion sentences.

    No LLM required. Used as a fallback when the LLM is unavailable or
    when pre-processing inputs before sending to the LLM.

    Args:
        text: Free-form text containing one or more facts.

    Returns:
        List of fact strings, each a single assertion.
    """
    if not text or not text.strip():
        return []

    # Step 1: split on sentence boundaries
    sentences = [s.strip() for s in _SENTENCE_END.split(text.strip()) if s.strip()]

    # Step 2: for each sentence, split on compound conjunctions
    atoms: list[str] = []
    for sentence in sentences:
        parts = [p.strip() for p in _COMPOUND_SPLITTERS.split(sentence) if p.strip()]
        if len(parts) == 1:
            atoms.append(parts[0])
        else:
            # Re-attach subject to each part if the part starts lowercase
            # (heuristic: subject was in first part)
            subject = _extract_subject(parts[0])
            for i, part in enumerate(parts):
                if i == 0:
                    atoms.append(part)
                elif part and part[0].islower() and subject:
                    atoms.append(f"{subject} {part}")
                else:
                    atoms.append(part)

    # Step 3: remove empty / too-short fragments
    return [a for a in atoms if len(a) > 5]


def _extract_subject(sentence: str) -> str:
    """Best-effort extraction of the grammatical subject from the first clause."""
    # Match "Name verb" or "Name and Name verb"
    m = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+\w', sentence)
    if m:
        return m.group(1)
    return ""


# ── Validation ───────────────────────────────────────────────────────────

def validate_fact(fact: str) -> tuple[bool, str]:
    """Check whether a fact meets atomicity, attribution, and temporal standards.

    Args:
        fact: The fact string to validate.

    Returns:
        (is_valid, reason_if_invalid). reason is empty string when valid.
    """
    if not fact or not fact.strip():
        return False, "empty fact"

    stripped = fact.strip()

    # Atomicity: should not contain compound conjunctions joining two assertions
    compound_match = _COMPOUND_SPLITTERS.search(stripped)
    if compound_match:
        return False, f"compound assertion — split on '{compound_match.group().strip()}'"

    # Attribution: should not use vague pronouns as the primary subject
    if _VAGUE_PRONOUNS.match(stripped):
        return False, "starts with vague pronoun — add explicit attribution"

    # Temporal resolution: relative dates should be resolved
    rel_temporal = _RELATIVE_TEMPORAL.search(stripped)
    if rel_temporal:
        term = rel_temporal.group(0)
        return False, f"unresolved temporal reference '{term}' — use absolute date"

    # Length sanity
    if len(stripped) < 8:
        return False, "too short to be a meaningful fact"

    return True, ""


# ── Deduplication ────────────────────────────────────────────────────────

def deduplicate_facts(
    new_facts: list[AtomicFact],
    existing: list[str],
    threshold: float = 0.85,
) -> list[AtomicFact]:
    """Remove new facts that are near-duplicate of existing ones.

    Uses word-level Jaccard similarity for fast approximate matching.

    Args:
        new_facts: Candidate AtomicFact objects to insert.
        existing: Already-stored fact strings.
        threshold: Jaccard similarity cutoff. Facts above this are dropped.

    Returns:
        Subset of new_facts that are sufficiently novel.
    """
    existing_tokens = [_tokenize(e) for e in existing]
    result: list[AtomicFact] = []

    for fact in new_facts:
        candidate_tokens = _tokenize(fact.content)
        is_dup = any(
            _jaccard(candidate_tokens, existing_tok) >= threshold
            for existing_tok in existing_tokens
        )
        if not is_dup:
            result.append(fact)
            # Add to existing so later facts in the same batch don't duplicate each other
            existing_tokens.append(candidate_tokens)

    return result


def _tokenize(text: str) -> frozenset[str]:
    """Lowercase word tokenization for Jaccard computation."""
    return frozenset(re.findall(r'\w+', text.lower()))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Word-level Jaccard similarity."""
    if not a and not b:
        return 1.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


# ── Entity extraction (lightweight, no NER dependency) ──────────────────

def _extract_entities(text: str) -> list[str]:
    """Extract capitalized proper-noun-like tokens as entity hints."""
    return re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
