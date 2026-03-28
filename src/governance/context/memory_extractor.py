"""Memory Extractor — 6-type structured memory extraction from conversations.

Stolen from OpenViking's auto-evolution mechanism: after each session,
extract structured memories across 6 categories. Uses local Ollama
(fast, free) with fallback to Claude Haiku.
"""
import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

MEMORY_CATEGORIES = {
    "profile": "Facts about the user: role, skills, background, knowledge level",
    "preferences": "User's preferred tools, workflows, coding styles, communication preferences",
    "entities": "People, projects, services, tools mentioned with meaningful context",
    "events": "Significant decisions, milestones, failures, discoveries that happened",
    "cases": "Problem → approach → outcome patterns (what was tried, what worked)",
    "patterns": "Recurring behaviors, rules the user follows, anti-patterns to avoid",
}

EXTRACTION_PROMPT = '''Analyze this conversation excerpt and extract structured memories.
For each category, extract 0-2 items. Only extract genuinely new, non-obvious information.
Skip categories with no clear signal.

Categories:
- profile: facts about the user (role, skills, background)
- preferences: user's preferred approaches or tools
- entities: people/projects/tools mentioned with meaningful context
- events: significant things that happened in this session
- cases: problem → approach → outcome patterns
- patterns: recurring behaviors or rules

Output valid JSON only, no markdown:
{"memories": [{"category": "...", "l0": "one line summary", "l1": "2-3 sentence detail", "tags": ["tag1", "tag2"]}]}

If nothing memorable, return: {"memories": []}

Conversation:
{conversation}'''


def extract_memories(conversation_text: str, use_local: bool = True) -> list[dict]:
    """Extract 6-type memories from conversation text.

    Args:
        conversation_text: The conversation to analyze (last ~2000 chars recommended)
        use_local: Try local Ollama first (faster, free)

    Returns:
        List of memory dicts with keys: category, l0, l1, tags
    """
    if not conversation_text or len(conversation_text.strip()) < 50:
        return []

    # Truncate to last ~4000 chars to keep prompt small
    text = conversation_text[-4000:] if len(conversation_text) > 4000 else conversation_text
    prompt = EXTRACTION_PROMPT.format(conversation=text)

    result_text = ""

    if use_local:
        result_text = _call_ollama(prompt)

    if not result_text:
        # Fallback: skip (don't call cloud API from a hook — too expensive)
        log.debug("memory_extractor: no local model available, skipping extraction")
        return []

    return _parse_extraction(result_text)


def _call_ollama(prompt: str, model: str = "qwen2.5:7b", timeout: int = 30) -> str:
    """Call local Ollama for extraction."""
    try:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 1024},
        }).encode()

        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read())
        return data.get("response", "")
    except Exception as e:
        log.debug(f"memory_extractor: ollama call failed: {e}")
        return ""


def _parse_extraction(text: str) -> list[dict]:
    """Parse LLM output into structured memory list."""
    # Try to find JSON in the response
    try:
        # Strip markdown code fences if present
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

        data = json.loads(clean)
        memories = data.get("memories", [])
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
                memories = data.get("memories", [])
            except json.JSONDecodeError:
                log.debug("memory_extractor: failed to parse LLM output as JSON")
                return []
        else:
            return []

    # Validate each memory
    valid = []
    for m in memories:
        if not isinstance(m, dict):
            continue
        category = m.get("category", "")
        l0 = m.get("l0", "")
        if category not in MEMORY_CATEGORIES or not l0:
            continue
        valid.append({
            "category": category,
            "l0": l0[:200],
            "l1": m.get("l1", "")[:1000],
            "tags": m.get("tags", [])[:5],
        })

    log.info(f"memory_extractor: extracted {len(valid)} memories from {len(text)} chars")
    return valid


def persist_memories(memories: list[dict], db_path: str = None, memory_dir: str = None):
    """Save extracted memories to DB and/or memory directory.

    Args:
        memories: List of memory dicts from extract_memories()
        db_path: Path to events.db (optional)
        memory_dir: Path to memory directory for .md files (optional)
    """
    if not memories:
        return

    now = datetime.now(timezone.utc).isoformat()

    # Save to DB if path provided
    if db_path:
        try:
            from src.storage.events_db import EventsDB
            db = EventsDB(db_path)
            for m in memories:
                db.add_agent_event(
                    task_id=0,  # session-level, no task
                    event_type="memory_extracted",
                    data={
                        "category": m["category"],
                        "l0": m["l0"],
                        "l1": m["l1"],
                        "tags": m["tags"],
                        "extracted_at": now,
                    },
                )
        except Exception as e:
            log.warning(f"memory_extractor: DB persist failed: {e}")

    # Save to memory directory as .md files
    if memory_dir:
        _persist_to_files(memories, Path(memory_dir), now)


def _persist_to_files(memories: list[dict], memory_dir: Path, timestamp: str):
    """Write memories as .md files with frontmatter."""
    if not memory_dir.exists():
        return

    for m in memories:
        category = m["category"]
        l0 = m["l0"]
        l1 = m["l1"]
        tags = m.get("tags", [])

        # Generate filename from category + first few words of l0
        slug = l0[:40].lower().replace(" ", "_").replace("/", "_")
        slug = "".join(c for c in slug if c.isalnum() or c == "_")
        filename = f"auto_{category}_{slug}.md"
        filepath = memory_dir / filename

        # Skip if file already exists (avoid duplicates)
        if filepath.exists():
            continue

        content = f"""---
name: {l0[:80]}
description: {l0}
type: {category}
l0: {l0}
---

{l1}
"""
        try:
            filepath.write_text(content, encoding="utf-8")
            log.info(f"memory_extractor: wrote {filename}")
        except Exception as e:
            log.warning(f"memory_extractor: failed to write {filename}: {e}")
