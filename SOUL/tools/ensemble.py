import asyncio
import json
import subprocess
import yaml
from pathlib import Path
from datetime import datetime

WORKERS_PATH = Path(".claude/reviewers/workers.yaml")
REVIEWERS_PATH = Path(".claude/reviewers/reviewers.yaml")


def load_registry() -> tuple[dict, dict]:
    """Read both YAML files and return (workers_dict, reviewers_dict)."""
    workers_data = yaml.safe_load(WORKERS_PATH.read_text(encoding="utf-8"))
    reviewers_data = yaml.safe_load(REVIEWERS_PATH.read_text(encoding="utf-8"))
    return workers_data["workers"], reviewers_data["reviewers"]


async def run_worker(worker_cfg: dict, payload: str, worker_index: int) -> dict:
    """Mock worker implementation.

    # TODO: replace with actual Claude CLI subprocess call
    This is the integration boundary — the real CLI call depends on environment.
    """
    return {
        "worker_index": worker_index,
        "verdict": "CONTINUE",
        "findings": [],
        "error": None,
    }


def synthesize_handler(worker_results: list[dict], handler_cfg: dict) -> dict:
    """Stub: consolidate worker findings via handler worker.

    # TODO: invoke handler worker with consolidated findings
    """
    return {
        "verdict": "CONTINUE",
        "findings": [r["findings"] for r in worker_results],
    }


def write_review_to_disk(review: dict, output_path: Path) -> None:
    """Write review JSON to output_path, creating parent dirs as needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(review, indent=2), encoding="utf-8")


async def run_ensemble(reviewer_name: str, payload: str) -> dict:
    """Fan out to all workers in parallel, synthesize, write to disk."""
    workers, reviewers = load_registry()

    reviewer_cfg = reviewers[reviewer_name]
    worker_name = reviewer_cfg["worker"]
    worker_count = reviewer_cfg["worker_count"]
    handler_name = reviewer_cfg["handler"]

    worker_cfg = workers[worker_name]
    handler_cfg = workers[handler_name]

    results = await asyncio.gather(
        *[run_worker(worker_cfg, payload, i) for i in range(worker_count)],
        return_exceptions=True,
    )

    successes = [r for r in results if isinstance(r, dict) and r.get("error") is None]

    if not successes:
        review = {
            "verdict": "DEGRADED_FATAL",
            "findings": [],
            "reason": "all workers failed",
        }
    else:
        review = synthesize_handler(successes, handler_cfg)

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(f".trash/reviews/{timestamp}-{reviewer_name}.json")
    write_review_to_disk(review, output_path)

    return review
