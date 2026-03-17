import os
import tempfile
import shutil
import pytest
from auto_tagger.progress import (
    load_progress,
    save_progress,
    init_progress,
    mark_batch_completed,
    mark_files_retry,
    get_pending_files,
    get_stats,
)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


class TestInitProgress:
    def test_creates_initial_state(self):
        progress = init_progress(total_files=100, file_paths=["/a.md", "/b.md"])
        assert progress["total_files"] == 100
        assert progress["processed"] == 0
        assert progress["skipped"] == 0
        assert progress["failed"] == 0
        assert progress["batches"] == []
        assert progress["new_tags_proposed"] == []
        assert progress["all_files"] == ["/a.md", "/b.md"]


class TestSaveLoadProgress:
    def test_roundtrip(self, tmp_dir):
        path = os.path.join(tmp_dir, "progress.json")
        progress = init_progress(total_files=10, file_paths=["/a.md"])
        save_progress(progress, path)
        loaded = load_progress(path)
        assert loaded == progress

    def test_load_missing_returns_none(self, tmp_dir):
        path = os.path.join(tmp_dir, "nonexistent.json")
        result = load_progress(path)
        assert result is None


class TestMarkBatchCompleted:
    def test_marks_completed(self):
        progress = init_progress(total_files=10, file_paths=[])
        progress["batches"].append({
            "id": 1,
            "files": ["/a.md", "/b.md"],
            "status": "processing",
        })
        progress = mark_batch_completed(progress, batch_id=1)
        assert progress["batches"][0]["status"] == "completed"
        assert progress["processed"] == 2


class TestMarkFilesRetry:
    def test_first_retry(self):
        progress = init_progress(total_files=10, file_paths=[])
        progress = mark_files_retry(progress, ["/a.md", "/b.md"])
        retry_batch = [b for b in progress["batches"] if b["status"] == "retry"]
        assert len(retry_batch) == 1
        assert set(retry_batch[0]["files"]) == {"/a.md", "/b.md"}
        assert retry_batch[0]["retry_count"] == 1

    def test_three_retries_becomes_failed(self):
        progress = init_progress(total_files=10, file_paths=[])
        # Simulate 3 retries of the same file
        for _ in range(3):
            progress = mark_files_retry(progress, ["/a.md"])
        # After 3rd retry, should be marked failed
        assert progress["failed"] == 1
        assert "/a.md" not in get_pending_files(progress)


class TestGetPendingFiles:
    def test_excludes_completed_and_failed(self):
        progress = init_progress(
            total_files=4,
            file_paths=["/a.md", "/b.md", "/c.md", "/d.md"],
        )
        # Mark /a.md as completed
        progress["batches"].append({
            "id": 1,
            "files": ["/a.md"],
            "status": "completed",
        })
        progress["processed"] = 1
        # Mark /b.md as failed
        progress["batches"].append({
            "id": 2,
            "files": ["/b.md"],
            "status": "failed",
        })
        progress["failed"] = 1
        # /c.md is retry
        progress["batches"].append({
            "id": 3,
            "files": ["/c.md"],
            "status": "retry",
            "retry_count": 1,
        })

        pending = get_pending_files(progress)
        assert "/a.md" not in pending  # completed
        assert "/b.md" not in pending  # failed
        assert "/c.md" in pending      # retry = still pending
        assert "/d.md" in pending      # never processed


class TestGetStats:
    def test_returns_summary(self):
        progress = init_progress(total_files=10, file_paths=[])
        progress["processed"] = 7
        progress["skipped"] = 2
        progress["failed"] = 1
        progress["new_tags_proposed"] = ["LegalQuant", "StableCoin"]
        stats = get_stats(progress)
        assert stats["total"] == 10
        assert stats["processed"] == 7
        assert stats["skipped"] == 2
        assert stats["failed"] == 1
        assert stats["new_tags"] == ["LegalQuant", "StableCoin"]
