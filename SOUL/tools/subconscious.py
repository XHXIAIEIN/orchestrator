"""
Subconscious — Memory Curator for Orchestrator

The Alzheimer's patient's personal nurse. Runs after each session to:
  --audit   : Fast, no LLM. Check duplicates, orphans, index consistency.
  --curate  : Local LLM. Intelligent merge/dedup/update suggestions.
  --deep    : Agent SDK. Full memory review with codebase access.
  --apply   : Apply pending recommendations from last curate/deep run.

Stolen from: letta-ai/claude-subconscious (dual-agent memory architecture)
Adapted to: pure local, no external platform dependency.

Usage:
    python -m SOUL.tools.subconscious --audit
    python -m SOUL.tools.subconscious --curate
    python -m SOUL.tools.subconscious --deep
"""

import argparse
import json
import logging
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

def _find_memory_dir() -> Path:
    """Find Claude auto-memory directory for this project."""
    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.exists():
        return Path(".")

    # Encode project path to Claude's dir name format
    proj_str = str(PROJECT_ROOT.resolve())
    encoded = proj_str.replace("\\", "-").replace(":", "-").replace("/", "-")

    candidate = projects_root / encoded / "memory"
    if candidate.exists():
        return candidate

    # Fuzzy: look for dirs containing 'orchestrator' with MEMORY.md
    for d in projects_root.iterdir():
        if "orchestrator" in d.name.lower():
            mem = d / "memory"
            if mem.exists() and (mem / "MEMORY.md").exists():
                return mem

    return Path(".")


MEMORY_DIR = _find_memory_dir()
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
RECOMMENDATIONS_PATH = DATA_DIR / "subconscious-recommendations.json"
AUDIT_LOG_PATH = DATA_DIR / "subconscious-audit.log"


# ── Audit Mode (no LLM) ───────────────────────────────────────────

def audit() -> dict:
    """Fast audit: check duplicates, orphans, index consistency.

    Returns dict with findings.
    """
    findings = {
        "duplicates": [],       # pairs of files with >80% similar descriptions
        "orphan_files": [],     # .md files not in MEMORY.md index
        "orphan_links": [],     # links in MEMORY.md pointing to missing files
        "empty_files": [],      # files with no content after frontmatter
        "index_lines": 0,
        "total_files": 0,
        "timestamp": datetime.now().isoformat(),
    }

    if not MEMORY_DIR.exists() or not MEMORY_INDEX.exists():
        findings["error"] = f"Memory dir not found: {MEMORY_DIR}"
        return findings

    # Read index
    index_text = MEMORY_INDEX.read_text(encoding="utf-8")
    index_lines = index_text.strip().split("\n")
    findings["index_lines"] = len(index_lines)

    # Extract linked filenames from index
    linked_files = set()
    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+\.md)\)")
    for line in index_lines:
        for match in link_pattern.finditer(line):
            linked_files.add(match.group(2))

    # Scan actual .md files (excluding MEMORY.md itself and .trash/)
    actual_files = set()
    for f in MEMORY_DIR.glob("*.md"):
        if f.name == "MEMORY.md":
            continue
        actual_files.add(f.name)

    # Orphan detection
    findings["orphan_files"] = sorted(actual_files - linked_files)
    findings["orphan_links"] = sorted(linked_files - actual_files)
    findings["total_files"] = len(actual_files)

    # Read all files, extract descriptions for similarity check
    file_meta = {}
    for fname in actual_files:
        fpath = MEMORY_DIR / fname
        try:
            content = fpath.read_text(encoding="utf-8")
        except Exception:
            continue

        # Parse frontmatter
        desc = ""
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1]
                body = parts[2].strip()
                for line in frontmatter.split("\n"):
                    if line.startswith("description:"):
                        desc = line[len("description:"):].strip()
                        break

        if not body:
            findings["empty_files"].append(fname)

        file_meta[fname] = {
            "description": desc,
            "body": body[:500],  # first 500 chars for comparison
        }

    # Duplicate detection (description similarity > 0.8)
    files = list(file_meta.keys())
    for i in range(len(files)):
        for j in range(i + 1, len(files)):
            a, b = files[i], files[j]
            desc_a = file_meta[a]["description"]
            desc_b = file_meta[b]["description"]
            if not desc_a or not desc_b:
                continue
            ratio = SequenceMatcher(None, desc_a.lower(), desc_b.lower()).ratio()
            if ratio > 0.8:
                findings["duplicates"].append({
                    "file_a": a,
                    "file_b": b,
                    "similarity": round(ratio, 2),
                    "desc_a": desc_a[:100],
                    "desc_b": desc_b[:100],
                })

    return findings


def print_audit(findings: dict):
    """Pretty-print audit results."""
    print(f"=== Subconscious Audit ({findings['timestamp']}) ===")
    print(f"Memory files: {findings['total_files']}  |  Index lines: {findings['index_lines']}")
    print()

    if findings.get("error"):
        print(f"ERROR: {findings['error']}")
        return

    issues = 0

    if findings["duplicates"]:
        print(f"⚠ Duplicates ({len(findings['duplicates'])} pairs):")
        for d in findings["duplicates"]:
            print(f"  {d['file_a']} <-> {d['file_b']}  ({d['similarity']:.0%})")
            print(f"    A: {d['desc_a']}")
            print(f"    B: {d['desc_b']}")
        issues += len(findings["duplicates"])
        print()

    if findings["orphan_files"]:
        print(f"⚠ Files not in index ({len(findings['orphan_files'])}):")
        for f in findings["orphan_files"]:
            print(f"  {f}")
        issues += len(findings["orphan_files"])
        print()

    if findings["orphan_links"]:
        print(f"⚠ Broken links in index ({len(findings['orphan_links'])}):")
        for f in findings["orphan_links"]:
            print(f"  {f}")
        issues += len(findings["orphan_links"])
        print()

    if findings["empty_files"]:
        print(f"⚠ Empty files ({len(findings['empty_files'])}):")
        for f in findings["empty_files"]:
            print(f"  {f}")
        issues += len(findings["empty_files"])
        print()

    if issues == 0:
        print("All clear. No issues found.")
    else:
        print(f"Total issues: {issues}")

    # Append to audit log
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(findings, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── Curate Mode (local LLM) ───────────────────────────────────────

CURATE_PROMPT = '''You are a memory curator for an AI assistant. Your job is to review the assistant's memory files and suggest improvements.

Current memory index (MEMORY.md):
{index}

Memory file contents:
{contents}

Analyze the memories and output a JSON list of recommendations. Each recommendation should be one of:
- "merge": two files should be combined into one
- "update": a file's content should be updated (e.g., description is vague)
- "stale": a file likely contains outdated information
- "redundant": a file duplicates information already in CLAUDE.md or derivable from code

Output format (valid JSON only, no markdown):
{{"recommendations": [
  {{"action": "merge", "files": ["file_a.md", "file_b.md"], "reason": "...", "suggested_name": "merged_file.md"}},
  {{"action": "stale", "file": "some_file.md", "reason": "..."}},
  {{"action": "update", "file": "some_file.md", "reason": "...", "suggestion": "..."}}
]}}

If everything looks good, return: {{"recommendations": []}}

Be conservative. Only flag things you're confident about.'''


def curate() -> list[dict]:
    """Use local LLM to intelligently review memories."""
    if not MEMORY_DIR.exists() or not MEMORY_INDEX.exists():
        print("ERROR: Memory directory not found")
        return []

    index = MEMORY_INDEX.read_text(encoding="utf-8")

    # Read all memory files
    contents_parts = []
    for f in sorted(MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            text = f.read_text(encoding="utf-8")
            # Truncate long files
            if len(text) > 500:
                text = text[:500] + "\n... (truncated)"
            contents_parts.append(f"### {f.name}\n{text}")
        except Exception:
            continue

    contents = "\n\n".join(contents_parts)

    # Total prompt size check — local models have limited context
    prompt = CURATE_PROMPT.format(index=index, contents=contents)
    if len(prompt) > 12000:
        # Trim contents to fit
        contents = contents[:8000] + "\n... (remaining files truncated)"
        prompt = CURATE_PROMPT.format(index=index, contents=contents)

    print(f"Sending {len(prompt)} chars to local LLM for curation...")

    result = _call_ollama(prompt, model="qwen2.5:7b", timeout=60)
    if not result:
        print("ERROR: Ollama unavailable or no response")
        return []

    # Parse recommendations
    recommendations = _parse_recommendations(result)

    if recommendations:
        # Save for later --apply
        RECOMMENDATIONS_PATH.write_text(
            json.dumps(recommendations, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nSaved {len(recommendations)} recommendations to {RECOMMENDATIONS_PATH}")
        print("Run with --apply to execute them.")
    else:
        print("No recommendations. Memories look clean.")

    return recommendations


def print_recommendations(recs: list[dict]):
    """Pretty-print curation recommendations."""
    for i, rec in enumerate(recs, 1):
        action = rec.get("action", "?")
        if action == "merge":
            files = rec.get("files", [])
            print(f"  {i}. MERGE: {' + '.join(files)} -> {rec.get('suggested_name', '?')}")
        elif action == "stale":
            print(f"  {i}. STALE: {rec.get('file', '?')}")
        elif action == "update":
            print(f"  {i}. UPDATE: {rec.get('file', '?')}")
        elif action == "redundant":
            print(f"  {i}. REDUNDANT: {rec.get('file', '?')}")
        print(f"     Reason: {rec.get('reason', 'N/A')}")
        if rec.get("suggestion"):
            print(f"     Suggestion: {rec['suggestion']}")
        print()


# ── Apply Mode ─────────────────────────────────────────────────────

def apply_recommendations():
    """Apply saved recommendations from last curate run."""
    if not RECOMMENDATIONS_PATH.exists():
        print("No pending recommendations. Run --curate first.")
        return

    recs = json.loads(RECOMMENDATIONS_PATH.read_text(encoding="utf-8"))
    if not recs:
        print("No recommendations to apply.")
        return

    print(f"Found {len(recs)} pending recommendations:")
    print_recommendations(recs)

    trash_dir = MEMORY_DIR / ".trash" / datetime.now().strftime("%Y-%m-%d-subconscious")
    trash_dir.mkdir(parents=True, exist_ok=True)

    applied = 0
    for rec in recs:
        action = rec.get("action")

        if action == "merge":
            files = rec.get("files", [])
            if len(files) < 2:
                continue
            # Move secondary files to trash, keep first
            for f in files[1:]:
                src = MEMORY_DIR / f
                if src.exists():
                    dst = trash_dir / f
                    src.rename(dst)
                    print(f"  Moved {f} -> .trash/")
                    applied += 1

                    # Remove from MEMORY.md index
                    _remove_from_index(f)

        elif action == "stale":
            fname = rec.get("file", "")
            src = MEMORY_DIR / fname
            if src.exists():
                dst = trash_dir / fname
                src.rename(dst)
                print(f"  Moved {fname} -> .trash/ (stale)")
                _remove_from_index(fname)
                applied += 1

        elif action == "redundant":
            fname = rec.get("file", "")
            src = MEMORY_DIR / fname
            if src.exists():
                dst = trash_dir / fname
                src.rename(dst)
                print(f"  Moved {fname} -> .trash/ (redundant)")
                _remove_from_index(fname)
                applied += 1

    print(f"\nApplied {applied} changes. Trash: {trash_dir}")

    # Clear recommendations
    RECOMMENDATIONS_PATH.unlink(missing_ok=True)


def _remove_from_index(filename: str):
    """Remove a file reference from MEMORY.md index."""
    if not MEMORY_INDEX.exists():
        return
    lines = MEMORY_INDEX.read_text(encoding="utf-8").split("\n")
    new_lines = [l for l in lines if filename not in l]
    if len(new_lines) < len(lines):
        MEMORY_INDEX.write_text("\n".join(new_lines), encoding="utf-8")


# ── Deep Mode (Agent SDK) ─────────────────────────────────────────

DEEP_SYSTEM_PROMPT = '''You are the Subconscious — a memory curator for an AI assistant called Orchestrator.

Your job: review all memory files, verify they are accurate and current, merge duplicates, remove stale entries, and update the MEMORY.md index.

Rules:
1. Read every memory file in the memory directory
2. Check if information is still accurate (grep the codebase if needed)
3. Merge files that cover the same topic
4. Move stale/outdated files to .trash/ (use mv, never delete directly)
5. Update MEMORY.md index to reflect changes
6. Keep the index under 200 lines
7. Write a brief report of what you changed

Memory directory: {memory_dir}
Project root: {project_root}

Be conservative. When in doubt, keep the file. The owner will review .trash/ later.'''


def deep_curate():
    """Full memory review using Agent SDK — can read codebase to verify memories."""
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
    except ImportError:
        print("ERROR: claude_agent_sdk not available. Install it or use --curate instead.")
        return

    import anyio

    system_prompt = DEEP_SYSTEM_PROMPT.format(
        memory_dir=str(MEMORY_DIR),
        project_root=str(PROJECT_ROOT),
    )

    prompt = (
        "Review and curate all memory files. "
        "Read each file, check for duplicates/staleness/accuracy, "
        "merge where appropriate, and update the index. "
        "Move cleaned files to .trash/ with today's date subfolder. "
        "Report what you changed at the end."
    )

    async def _run():
        result_text = ""
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(PROJECT_ROOT),
                system_prompt=system_prompt,
                max_turns=15,
                permission_mode="bypassPermissions",
                allowed_tools=[
                    "Read", "Grep", "Glob", "Edit", "Write", "Bash",
                ],
            ),
        ):
            # Print streaming output
            if hasattr(message, "content"):
                text = getattr(message, "content", "")
                if text:
                    print(text, end="", flush=True)
                    result_text += text
        return result_text

    print("Starting deep memory curation via Agent SDK...")
    print("=" * 60)
    result = anyio.run(_run)
    print("\n" + "=" * 60)
    print("Deep curation complete.")


# ── Shared Helpers ─────────────────────────────────────────────────

def _call_ollama(prompt: str, model: str = "qwen2.5:7b", timeout: int = 30) -> str:
    """Call local Ollama."""
    try:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 2048},
        }).encode()

        req = urllib.request.Request(
            f"{os.environ.get('OLLAMA_HOST', 'http://localhost:11434')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read())
        return data.get("response", "")
    except Exception as e:
        log.debug(f"subconscious: ollama call failed: {e}")
        return ""


def _parse_recommendations(text: str) -> list[dict]:
    """Parse LLM output into recommendation list."""
    # Strip thinking tags if present
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    try:
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

        data = json.loads(clean)
        return data.get("recommendations", [])
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
                return data.get("recommendations", [])
            except json.JSONDecodeError:
                pass
    return []


# ── Session counter (for periodic curation trigger) ────────────────

COUNTER_PATH = DATA_DIR / "subconscious-session-count"

def should_curate(every_n: int = 5) -> bool:
    """Check if we should run curation this session (every N sessions)."""
    try:
        count = int(COUNTER_PATH.read_text().strip()) if COUNTER_PATH.exists() else 0
    except (ValueError, OSError):
        count = 0

    count += 1
    COUNTER_PATH.write_text(str(count))

    return count % every_n == 0


# ── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Subconscious — Memory Curator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--audit", action="store_true", help="Fast audit (no LLM)")
    group.add_argument("--curate", action="store_true", help="LLM-powered curation")
    group.add_argument("--deep", action="store_true", help="Full Agent SDK review")
    group.add_argument("--apply", action="store_true", help="Apply pending recommendations")
    group.add_argument("--auto", action="store_true", help="Auto mode: audit always, curate every 5 sessions")

    args = parser.parse_args()

    if args.audit:
        findings = audit()
        print_audit(findings)

    elif args.curate:
        recs = curate()
        if recs:
            print_recommendations(recs)

    elif args.deep:
        deep_curate()

    elif args.apply:
        apply_recommendations()

    elif args.auto:
        # Always audit
        findings = audit()
        issues = (
            len(findings.get("duplicates", []))
            + len(findings.get("orphan_files", []))
            + len(findings.get("orphan_links", []))
            + len(findings.get("empty_files", []))
        )

        if issues > 0:
            print_audit(findings)

        # Curate every 5 sessions (or if audit found issues)
        if should_curate(every_n=5) or issues >= 3:
            print("\n--- Triggering curation (periodic or issue threshold) ---\n")
            recs = curate()
            if recs:
                print_recommendations(recs)


if __name__ == "__main__":
    main()
