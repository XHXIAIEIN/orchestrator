"""Clawvard Exam Runner — handles API plumbing, saves results reliably.

Usage:
    from src.exam.runner import ExamRunner
    runner = ExamRunner()
    questions = runner.start()       # returns first batch questions
    questions = runner.submit([       # submit answers, get next batch
        {"questionId": "xxx", "answer": "..."},
        ...
    ])
    # When done, runner.report contains final results
"""
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

API_BASE = "https://clawvard.school/api/exam"


def _find_repo_root() -> Path:
    """Walk up from this file until we find a directory containing both
    'departments/' and 'src/' subdirectories."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "departments").is_dir() and (parent / "src").is_dir():
            return parent
    # Fallback: two levels up from src/exam/
    return here.parent.parent.parent


RUNS_DIR: Path = _find_repo_root() / "data" / "exam-runs"


class ExamRunner:
    def __init__(self, runs_dir: Path | None = None) -> None:
        self.runs_dir: Path = runs_dir if runs_dir is not None else RUNS_DIR
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.exam_id: str | None = None
        self.hash: str | None = None
        self.batch_num: int = 0
        self.results: list[dict[str, Any]] = []
        self.report: dict[str, Any] | None = None

    def _post(self, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{API_BASE}/{endpoint}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _save(self, name: str, obj: dict[str, Any]) -> Path:
        path = self.runs_dir / name
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def start(self) -> list[dict[str, Any]]:
        result = self._post("start")
        self.exam_id = result["examId"]
        self.hash = result["hash"]
        self._save(f"{self.exam_id}_start.json", result)
        return result["batch"]

    def submit(self, answers: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        self.batch_num += 1
        payload: dict[str, Any] = {
            "examId": self.exam_id,
            "hash": self.hash,
            "answers": answers,
        }
        result = self._post("batch-answer", payload)

        # Save immediately after successful API call
        self._save(
            f"{self.exam_id}_batch{self.batch_num}.json",
            {
                "submitted": answers,
                "response": result,
                "timestamp": datetime.now().isoformat(),
            },
        )

        # Update hash
        self.hash = result.get("hash")
        self.results.append(result)

        if result.get("examComplete"):
            self.report = result
            self._save(f"{self.exam_id}_final.json", result)
            return None

        return result.get("nextBatch")
