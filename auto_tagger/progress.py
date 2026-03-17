"""JSON-based progress tracking for batch processing with resume support."""

import json
import os


def init_progress(total_files: int, file_paths: list[str]) -> dict:
    """Create a fresh progress state."""
    return {
        "total_files": total_files,
        "processed": 0,
        "skipped": 0,
        "failed": 0,
        "batches": [],
        "new_tags_proposed": [],
        "all_files": file_paths,
        "failed_files": [],
    }


def save_progress(progress: dict, path: str) -> None:
    """Save progress dict to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def load_progress(path: str) -> dict | None:
    """
    Load progress from JSON file.
    Returns None if file does not exist.
    """
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def mark_batch_completed(progress: dict, batch_id: int) -> dict:
    """
    Mark a batch as completed and update processed count.
    """
    for batch in progress["batches"]:
        if batch["id"] == batch_id:
            batch["status"] = "completed"
            progress["processed"] += len(batch["files"])
            break
    return progress


def mark_files_retry(progress: dict, file_paths: list[str]) -> dict:
    """
    Mark files for retry. Increments retry_count.
    If a file reaches 3 retries, it is marked as failed.
    """
    files_to_retry = []
    files_to_fail = []

    for fp in file_paths:
        # Find existing retry count for this file
        retry_count = 0
        for batch in progress["batches"]:
            if batch.get("status") == "retry" and fp in batch["files"]:
                retry_count = batch.get("retry_count", 0)
                # Remove from old retry batch
                batch["files"].remove(fp)
                if not batch["files"]:
                    progress["batches"].remove(batch)
                break

        retry_count += 1
        if retry_count >= 3:
            files_to_fail.append(fp)
        else:
            files_to_retry.append((fp, retry_count))

    # Add retry batch if any
    if files_to_retry:
        max_retry = max(rc for _, rc in files_to_retry)
        batch_id = max(
            (b["id"] for b in progress["batches"]),
            default=0,
        ) + 1
        progress["batches"].append({
            "id": batch_id,
            "files": [fp for fp, _ in files_to_retry],
            "status": "retry",
            "retry_count": max_retry,
        })

    # Mark failed files
    for fp in files_to_fail:
        progress["failed"] += 1
        if fp not in progress.get("failed_files", []):
            progress.setdefault("failed_files", []).append(fp)
        batch_id = max(
            (b["id"] for b in progress["batches"]),
            default=0,
        ) + 1
        progress["batches"].append({
            "id": batch_id,
            "files": [fp],
            "status": "failed",
        })

    return progress


def get_pending_files(progress: dict) -> list[str]:
    """
    Return file paths that are not yet completed or failed.
    Includes: never processed + retry status.
    """
    completed_files = set()
    failed_files = set(progress.get("failed_files", []))
    retry_files = set()

    for batch in progress["batches"]:
        if batch["status"] == "completed":
            completed_files.update(batch["files"])
        elif batch["status"] == "failed":
            failed_files.update(batch["files"])
        elif batch["status"] == "retry":
            retry_files.update(batch["files"])

    done = completed_files | failed_files
    # Pending = all files not done (retry files are included)
    pending = [f for f in progress.get("all_files", []) if f not in done]
    # Also include retry files that might not be in all_files
    for rf in retry_files:
        if rf not in pending and rf not in done:
            pending.append(rf)

    return pending


def get_stats(progress: dict) -> dict:
    """Return summary statistics."""
    return {
        "total": progress["total_files"],
        "processed": progress["processed"],
        "skipped": progress["skipped"],
        "failed": progress["failed"],
        "new_tags": progress["new_tags_proposed"],
    }
