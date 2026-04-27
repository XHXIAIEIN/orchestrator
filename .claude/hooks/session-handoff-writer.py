#!/usr/bin/env python3
"""Stop hook — write per-session handoff if pending todos remain.

Reads the transcript at session-stop time, finds the most recent TodoWrite
state, and if any todo is pending or in_progress, writes a handoff file
under `.remember/handoff/<branch-slug>--<short-session>.md` with:

  - A pasteable opening prompt that names the exact handoff path
    (so the owner does not have to guess which one to read).
  - Pending todos (in_progress first), branch, HEAD, files touched,
    last assistant text, sessionId, cwd.

It also updates `.remember/handoff/INDEX.md` — one row per active handoff
so the owner can scan all parallel sessions at a glance.

Multi-worktree-safe: each branch in each worktree gets its own handoff file
(branch slug + short sessionId), so two sessions on different topics never
overwrite each other. If two sessions share a branch, the sessionId disambiguates.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


HANDOFF_DIR = ".remember/handoff"
INDEX_FILE = "INDEX.md"


def parse_transcript(path: str) -> dict:
    """Return latest-state summary from JSONL transcript."""
    out = {
        "todos": [],
        "files": [],
        "last_text": "",
        "branch": "",
        "session_id": "",
        "cwd": "",
        "first_user_msg": "",
    }
    seen_files: set[str] = set()
    files: list[str] = []

    if not path or not os.path.exists(path):
        return out

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return out

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("gitBranch"):
            out["branch"] = entry["gitBranch"]
        if entry.get("sessionId"):
            out["session_id"] = entry["sessionId"]
        if entry.get("cwd"):
            out["cwd"] = entry["cwd"]

        msg = entry.get("message") or {}
        content = msg.get("content")
        etype = entry.get("type")

        if isinstance(content, str) and content.strip():
            if etype == "assistant":
                out["last_text"] = content
            elif etype == "user" and not out["first_user_msg"]:
                out["first_user_msg"] = content

        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")

            if btype == "text":
                txt = block.get("text") or ""
                if txt.strip() and etype == "assistant":
                    out["last_text"] = txt
                if txt.strip() and etype == "user" and not out["first_user_msg"]:
                    out["first_user_msg"] = txt

            if btype != "tool_use":
                continue
            name = block.get("name", "")
            inp = block.get("input") or {}

            if name == "TodoWrite":
                ts = inp.get("todos")
                if isinstance(ts, list):
                    out["todos"] = ts

            if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                fp = inp.get("file_path") or inp.get("notebook_path") or ""
                if fp and fp not in seen_files:
                    seen_files.add(fp)
                    files.append(fp)

    out["files"] = files
    return out


def git(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def find_active_plan(files: list[str]) -> str:
    for fp in reversed(files):
        norm = fp.replace("\\", "/")
        if "/plans/" in norm and norm.endswith(".md"):
            return fp
        if "/SOUL/public/prompts/session_handoff" in norm:
            return fp
        if "/docs/superpowers/plans/" in norm and norm.endswith(".md"):
            return fp
    return ""


def slugify_branch(branch: str) -> str:
    if not branch:
        return "no-branch"
    slug = branch.replace("/", "--").replace("\\", "--")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug)
    slug = slug.strip(".-_") or "no-branch"
    return slug[:60]


def short_session(session_id: str) -> str:
    return (session_id or "anon").split("-")[0][:8] or "anon"


def topic_from_first_user_msg(text: str) -> str:
    if not text:
        return ""
    first_line = text.strip().splitlines()[0]
    return first_line[:80]


def render(
    pending: list[dict],
    branch: str,
    head: str,
    files: list[str],
    plan_hint: str,
    last_text: str,
    timestamp: str,
    session_id: str,
    cwd: str,
    handoff_rel: str,
    topic: str,
) -> str:
    lines: list[str] = []
    lines.append(f"# Session Handoff — {timestamp}")
    lines.append("")
    lines.append("## Opening prompt (paste into next session)")
    lines.append("")
    lines.append("```")
    if plan_hint:
        lines.append(f"读 {handoff_rel} 和 {plan_hint}，接着干。")
    else:
        lines.append(f"读 {handoff_rel}，接着干。")
    lines.append("```")
    lines.append("")

    lines.append("## Identity")
    if branch:
        lines.append(f"- branch: `{branch}`")
    if cwd:
        lines.append(f"- cwd: `{cwd}`")
    if session_id:
        lines.append(f"- session: `{session_id}`")
    if topic:
        lines.append(f"- topic: {topic}")
    if head:
        lines.append(f"- HEAD: `{head}`")
    lines.append(f"- saved at: {timestamp}")
    lines.append("")

    in_progress = [t for t in pending if t.get("status") == "in_progress"]
    pending_only = [t for t in pending if t.get("status") == "pending"]

    lines.append(f"## Pending todos ({len(pending)})")
    for t in in_progress + pending_only:
        status = t.get("status", "?")
        subject = t.get("activeForm") or t.get("content") or "?"
        marker = ">" if status == "in_progress" else "-"
        lines.append(f"{marker} [{status}] {subject}")
    lines.append("")

    if files:
        lines.append("## Files touched this session")
        for fp in files[-15:]:
            lines.append(f"- `{fp}`")
        lines.append("")

    if plan_hint:
        lines.append("## Active plan")
        lines.append(f"- `{plan_hint}`")
        lines.append("")

    if last_text:
        snippet = last_text.strip()[:400]
        lines.append("## Last working context")
        for s in snippet.splitlines():
            lines.append(f"> {s}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def update_index(handoff_dir: Path, project_dir: Path) -> None:
    """Rewrite INDEX.md to reflect every handoff currently on disk."""
    rows: list[tuple[float, str]] = []
    for md in sorted(handoff_dir.glob("*.md")):
        if md.name == INDEX_FILE:
            continue
        try:
            text = md.read_text(encoding="utf-8")
            mtime = md.stat().st_mtime
        except OSError:
            continue

        branch = _grep_first(text, r"- branch: `([^`]+)`") or "?"
        topic = _grep_first(text, r"- topic: (.+)") or ""
        saved = _grep_first(text, r"- saved at: (.+)") or "?"
        pending_n = _grep_first(text, r"## Pending todos \((\d+)\)") or "?"
        try:
            rel = md.relative_to(project_dir).as_posix()
        except ValueError:
            rel = md.as_posix()
        rows.append((mtime, f"| `{branch}` | {pending_n} | {saved} | {topic[:60]} | `{rel}` |"))

    rows.sort(key=lambda r: r[0], reverse=True)

    body = ["# Handoff Index", "", "Active handoffs across all parallel sessions. Newest first.", ""]
    if not rows:
        body.append("_No active handoffs — every session finished its todos._")
        body.append("")
    else:
        body.append("| Branch | Pending | Saved at | Topic | File |")
        body.append("|--------|---------|----------|-------|------|")
        for _, row in rows:
            body.append(row)
        body.append("")

    try:
        (handoff_dir / INDEX_FILE).write_text("\n".join(body), encoding="utf-8")
    except OSError:
        pass


def _grep_first(text: str, pattern: str) -> str:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


def cleanup_legacy(remember_dir: Path) -> None:
    """Remove the old single-file handoff if it exists (migration)."""
    legacy = remember_dir / "next-session.md"
    if legacy.exists():
        try:
            legacy.unlink()
        except OSError:
            pass


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    cwd_raw = data.get("cwd") or os.getcwd()
    project_dir = Path(cwd_raw)
    transcript_path = data.get("transcript_path", "")

    summary = parse_transcript(transcript_path)
    todos = summary["todos"]
    files = summary["files"]
    branch = summary["branch"] or git(["branch", "--show-current"], project_dir)
    session_id = summary["session_id"] or data.get("session_id", "")
    last_text = summary["last_text"]

    remember_dir = project_dir / ".remember"
    handoff_dir = remember_dir / "handoff"
    cleanup_legacy(remember_dir)

    slug = slugify_branch(branch)
    sid = short_session(session_id)
    handoff_name = f"{slug}--{sid}.md"
    handoff_path = handoff_dir / handoff_name
    handoff_rel = handoff_path.relative_to(project_dir).as_posix()

    pending = [
        t for t in todos
        if isinstance(t, dict) and t.get("status") in ("pending", "in_progress")
    ]

    if not pending:
        if handoff_path.exists():
            try:
                handoff_path.unlink()
                print(
                    f"[handoff] 任务全完，清掉 {handoff_rel}",
                    file=sys.stderr,
                )
            except OSError:
                pass
        if handoff_dir.exists():
            update_index(handoff_dir, project_dir)
        return

    head = git(["log", "-1", "--format=%h %s"], project_dir)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    plan_hint = find_active_plan(files)
    topic = topic_from_first_user_msg(summary["first_user_msg"])

    body = render(
        pending=pending,
        branch=branch,
        head=head,
        files=files,
        plan_hint=plan_hint,
        last_text=last_text,
        timestamp=timestamp,
        session_id=session_id,
        cwd=cwd_raw,
        handoff_rel=handoff_rel,
        topic=topic,
    )

    try:
        handoff_dir.mkdir(parents=True, exist_ok=True)
        handoff_path.write_text(body, encoding="utf-8")
    except OSError as e:
        print(f"[handoff] 写入失败: {e}", file=sys.stderr)
        return

    update_index(handoff_dir, project_dir)

    n_total = len(pending)
    n_active = sum(1 for t in pending if t.get("status") == "in_progress")
    suffix = f"（{n_active} 个进行中）" if n_active else ""
    print(
        f"[handoff] {n_total} 个未完成 → {handoff_rel}{suffix}。"
        f" 索引：.remember/handoff/INDEX.md。"
        f" 下次粘『读 {handoff_rel}，接着干』。",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
