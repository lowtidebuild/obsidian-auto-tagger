"""Insert topic/theme tags into Obsidian note tag lines (idempotent, atomic write)."""

import os
import tempfile


def insert_tags(
    file_path: str,
    tag_line_num: int,
    topics: list[str],
    themes: list[str],
    dry_run: bool = False,
) -> dict:
    """
    Append #topic/... and #theme/... tags to the tag line of a .md file.

    Idempotent: existing topic/theme tags are not duplicated.
    Atomic: writes to tempfile first, then renames.
    Line count is preserved (same-line append).

    Args:
        file_path: Path to .md file.
        tag_line_num: 0-indexed line number of the tag line.
        topics: e.g. ["Law", "AI"]
        themes: e.g. ["LegalTech", "BusinessModelInnovation"]
        dry_run: If True, return before/after but do not modify file.

    Returns:
        {
            "file": file_path,
            "before": original tag line,
            "after": modified tag line,
            "written": bool
        }
    """
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    original_line = lines[tag_line_num]
    before = original_line.rstrip("\n")

    # Build new tags to add, skipping already-present ones
    new_tags = []
    for t in topics:
        tag = f"#topic/{t}"
        if tag not in before:
            new_tags.append(tag)
    for t in themes:
        tag = f"#theme/{t}"
        if tag not in before:
            new_tags.append(tag)

    # Nothing to add
    if not new_tags:
        return {
            "file": file_path,
            "before": before,
            "after": before,
            "written": False,
        }

    # Append tags to same line
    after = before + " " + " ".join(new_tags)

    if dry_run:
        return {
            "file": file_path,
            "before": before,
            "after": after,
            "written": False,
        }

    # Replace the line
    lines[tag_line_num] = after + "\n"

    # Atomic write: tempfile in same directory, then rename
    dir_name = os.path.dirname(file_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
            tmp_f.writelines(lines)

        # Verify line count
        with open(tmp_path, "r", encoding="utf-8") as check_f:
            new_line_count = len(check_f.readlines())
        with open(file_path, "r", encoding="utf-8") as orig_f:
            orig_line_count = len(orig_f.readlines())

        if new_line_count != orig_line_count:
            raise IOError(
                f"Line count mismatch: original={orig_line_count}, new={new_line_count}"
            )

        os.replace(tmp_path, file_path)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return {
        "file": file_path,
        "before": before,
        "after": after,
        "written": True,
    }


def insert_tags_dynamic(
    file_path: str,
    tag_line_num: int,
    tags: dict[str, list[str]],
    dry_run: bool = False,
) -> dict:
    """
    Insert tags with arbitrary prefixes.

    Args:
        tags: {"prefix": ["Value1", "Value2"]} e.g. {"topic": ["Law"], "theme": ["X"]}
    """
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    original_line = lines[tag_line_num]
    before = original_line.rstrip("\n")

    new_tags = []
    for prefix, values in tags.items():
        for v in values:
            tag = f"#{prefix}/{v}"
            if tag not in before:
                new_tags.append(tag)

    if not new_tags:
        return {"file": file_path, "before": before, "after": before, "written": False}

    after = before + " " + " ".join(new_tags)

    if dry_run:
        return {"file": file_path, "before": before, "after": after, "written": False}

    lines[tag_line_num] = after + "\n"

    dir_name = os.path.dirname(file_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
            tmp_f.writelines(lines)

        with open(tmp_path, "r", encoding="utf-8") as check_f:
            new_line_count = len(check_f.readlines())
        with open(file_path, "r", encoding="utf-8") as orig_f:
            orig_line_count = len(orig_f.readlines())

        if new_line_count != orig_line_count:
            raise IOError(f"Line count mismatch: original={orig_line_count}, new={new_line_count}")

        os.replace(tmp_path, file_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return {"file": file_path, "before": before, "after": after, "written": True}
