import subprocess
import pytest
from src.collectors.git_collector import GitCollector
from src.storage.events_db import EventsDB

_SILENT = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def make_fake_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, **_SILENT)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, **_SILENT)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, **_SILENT)
    (repo / "file.py").write_text("print('hello')")
    subprocess.run(["git", "add", "."], cwd=repo, **_SILENT)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, **_SILENT)
    return repo


def test_collector_finds_commits(tmp_path):
    make_fake_repo(tmp_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = GitCollector(db=db, search_paths=[str(tmp_path)])
    count = collector.collect()
    assert count >= 1


def test_collector_deduplicates(tmp_path):
    make_fake_repo(tmp_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = GitCollector(db=db, search_paths=[str(tmp_path)])
    collector.collect()
    count2 = collector.collect()
    assert count2 == 0
