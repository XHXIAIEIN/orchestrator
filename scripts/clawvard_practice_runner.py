"""Clawvard practice runner — dispatches batches through Governor pipeline sequentially.

Handles hash chain, nextBatch extraction, and score tracking automatically.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.events_db import EventsDB

DB_PATH = str(Path(__file__).parent.parent / "data" / "events.db")


def _extract_json_with_hash(text: str) -> dict | None:
    """Extract the API response JSON using balanced brace matching.

    Handles nested triple backticks inside JSON string values that break
    markdown code block regex parsing.
    """
    # Find all positions where {"results" or {"hash" starts
    candidates = []
    for marker in ['"results"', '"hash"']:
        idx = 0
        while True:
            pos = text.find(marker, idx)
            if pos == -1:
                break
            # Walk back to find the opening brace
            brace_pos = text.rfind('{', max(0, pos - 50), pos)
            if brace_pos >= 0:
                candidates.append(brace_pos)
            idx = pos + 1

    for start in sorted(set(candidates)):
        # Walk forward with brace counting
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_string:
                escape = True
                continue
            if c == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start:i+1])
                        if "hash" in data:
                            return data
                    except json.JSONDecodeError:
                        break
    return None


def dispatch_batch(db, practice_id, hash_val, task_order, current_index, questions,
                   chain_from: int | None = None):
    """Dispatch a single batch through Governor and return (scores, new_hash, next_batch, task_id)."""
    from scripts.dispatch import dispatch_raw

    # Build question descriptions
    q_descs = []
    for i, q in enumerate(questions):
        q_descs.append(f"Q{i+1} ({q['id']} - {q['name']}): {q['prompt'][:500]}")

    task_order_str = json.dumps(task_order)
    prompt = f"""Answer these {len(questions)} Clawvard practice questions and submit via API.
Print the COMPLETE raw JSON response from the API after submission (every field including hash, results, nextBatch).

Session:
- practiceId: {practice_id}
- hash: {hash_val}
- taskOrder: {task_order_str}
- currentIndex: {current_index}

Questions:
{chr(10).join(q_descs)}

Submit via curl:
curl -s -X POST 'https://clawvard.school/api/practice/answer' \\
  -H 'Content-Type: application/json' \\
  -d '{{"practiceId":"{practice_id}","hash":"{hash_val}","taskOrder":{task_order_str},"currentIndex":{current_index},"answers":[{",".join(f'{{"questionId":"{q["id"]}","answer":"YOUR_ANSWER"}}' for q in questions)}]}}'

CRITICAL: Print the ENTIRE JSON response. Target: 90%+."""

    dim = questions[0].get("dimension", "unknown")
    action = f"Clawvard {dim} batch idx={current_index}"

    result = dispatch_raw(prompt, "engineering", action, "high", "react", db,
                          skip_scrutiny=True,
                          tier="heavy",
                          chain_from=chain_from)

    task_id = result.get("task_id")
    if not task_id:
        print(f"  DISPATCH FAILED for {dim} batch")
        return None, hash_val, None, None

    # Auto-approve
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    db.update_task(task_id, approved_at=now, status="running")
    from src.governance.governor import Governor
    governor = Governor(db=db)
    governor.execute_task_async(task_id)

    # Wait for completion
    deadline = time.time() + 300
    while time.time() < deadline:
        task = db.get_task(task_id)
        status = task.get("status", "unknown") if task else "not_found"
        if status in ("done", "failed", "scrutiny_failed", "review_rejected", "gate_failed"):
            break
        time.sleep(5)

    task = db.get_task(task_id)
    output = task.get("output", "") if task else ""
    print(f"  Task #{task_id} [{task.get('status')}] output: {len(output)} chars")

    # Extract hash and nextBatch from output using balanced brace matching
    new_hash = hash_val
    next_batch = None
    scores = []

    data = _extract_json_with_hash(output)
    if data:
        new_hash = data.get("hash", hash_val)
        next_batch = data.get("nextBatch")
        scores = data.get("results", [])
    else:
        # Fallback: extract hash with regex
        hash_match = re.search(r'"hash"\s*:\s*"([a-f0-9]{64})"', output)
        if hash_match:
            new_hash = hash_match.group(1)

    return scores, new_hash, next_batch, task_id


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--practice-id", default="prac-62834b90")
    parser.add_argument("--hash", default="cae9055b16a502ab6aa24612b0fdf0ffe3039e128c1913da86a1717b7bb58755")
    parser.add_argument("--task-order", default='["und-43","und-34","ref-41","ref-09","too-42","too-08","exe-41","exe-06","eq-44","eq-07","ret-41","ret-01","rea-41","rea-30","mem-40","mem-36"]')
    parser.add_argument("--resume-from-task", type=int, default=None,
                        help="Resume from a completed task ID — reads its output for hash/nextBatch")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--first-batch", type=str, default=None)
    parser.add_argument("--start-batch-num", type=int, default=0)
    args = parser.parse_args()

    practice_id = args.practice_id
    task_order = json.loads(args.task_order)
    db = EventsDB(DB_PATH)

    # Resume from a previous task's output
    if args.resume_from_task:
        t = db.get_task(args.resume_from_task)
        if t and t.get("output"):
            data = _extract_json_with_hash(t["output"])
            if data:
                current_hash = data["hash"]
                current_index = data.get("currentIndex", args.start_index)
                current_batch = data.get("nextBatch")
                print(f"Resumed from task #{args.resume_from_task}: hash=...{current_hash[-16:]}, index={current_index}, batch={len(current_batch or [])} questions")
            else:
                print(f"ERROR: Could not parse task #{args.resume_from_task} output")
                return
        else:
            print(f"ERROR: Task #{args.resume_from_task} not found or no output")
            return
    else:
        current_hash = args.hash
        current_index = args.start_index
        if args.first_batch:
            current_batch = json.loads(args.first_batch)
        else:
            current_batch = [
                {"id": "und-43", "name": "Implicit Requirement", "dimension": "understanding",
                 "prompt": "User story: 'As a user, I want to upload my profile photo so others can recognise me.' Which implicit requirement is most critical to address before development? A) Photo should be PNG B) System must handle image resizing, storage limits, and content moderation for inappropriate images C) Users should add filters D) Upload button should be blue"},
                {"id": "und-34", "name": "Interpret Statistical Claims", "dimension": "understanding",
                 "prompt": "Evaluate an A/B test report for validity. Test: New checkout flow B vs current A. Duration: 3 days. 1247 users/variant. A: 3.2% (40 conversions), B: 4.1% (51 conversions). +28.1% improvement. p=0.048. Recommendation: Ship B for $2.4M revenue. Issues: started on Black Friday, stopped early at significance, mobile excluded due to tracking bug, 3 error users removed from B."}
            ]

    all_scores = []
    batch_num = args.start_batch_num
    prev_task_id = None

    while current_batch:
        batch_num += 1
        dim = current_batch[0].get("dimension", "?")
        print(f"\n=== Batch {batch_num}/8: {dim} (index={current_index}) ===")

        scores, new_hash, next_batch, batch_task_id = dispatch_batch(
            db, practice_id, current_hash, task_order, current_index, current_batch,
            chain_from=prev_task_id,
        )
        prev_task_id = batch_task_id

        if scores:
            for s in scores:
                print(f"  {s.get('questionId')}: {s.get('score')}/{s.get('maxScore')} - {s.get('feedback', '')[:100]}")
                all_scores.append(s)

        if new_hash != current_hash:
            print(f"  Hash updated: ...{new_hash[-16:]}")
            current_hash = new_hash
        else:
            print(f"  WARNING: Hash unchanged — chain may be broken")

        current_index += 2
        current_batch = next_batch

        if not next_batch:
            print(f"\n  No nextBatch — practice may be complete or chain broken")
            break

    # Final summary
    print("\n" + "=" * 60)
    print("PRACTICE COMPLETE — SCORE SUMMARY")
    print("=" * 60)
    total = sum(s.get("score", 0) for s in all_scores)
    max_total = sum(s.get("maxScore", 0) for s in all_scores)
    for s in all_scores:
        status = "✓" if s.get("status") == "pass" else "~"
        print(f"  {status} {s.get('questionId')}: {s.get('score')}/{s.get('maxScore')}")
    print(f"\nTOTAL: {total}/{max_total} ({total/max_total*100:.0f}%)" if max_total > 0 else "No scores recorded")


if __name__ == "__main__":
    main()
