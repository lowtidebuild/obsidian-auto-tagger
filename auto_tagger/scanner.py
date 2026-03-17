"""Vault structure auto-detection for auto tagger init command."""

import os
import re
from collections import Counter

from auto_tagger.config import default_config

# Pattern: #prefix/Value (e.g., #topic/Economics, #theme/SupplyChain)
PREFIXED_TAG_PATTERN = re.compile(r"#([a-zA-Z]+)/([A-Za-z0-9\uAC00-\uD7A3_]+)")

# Pattern: any tag line start
TAG_LINE_START = re.compile(r"^#[^\s#]")

# Minimum number of .md files for a directory to be considered a "note directory"
MIN_NOTES_PER_DIR = 1


def _find_all_md_files(vault_path: str) -> list[str]:
    """Recursively find all .md files in the vault."""
    md_files = []
    for root, _, files in os.walk(vault_path):
        for f in sorted(files):
            if f.endswith(".md"):
                md_files.append(os.path.join(root, f))
    return md_files


def _has_frontmatter(file_path: str) -> bool:
    """Check if a file has YAML frontmatter (starts with ---)."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        return first_line == "---"
    except Exception:
        return False


def _extract_prefixed_tags(file_path: str) -> list[tuple[str, str]]:
    """
    Extract all #prefix/Value tags from a file.
    Returns list of (prefix, value) tuples.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return PREFIXED_TAG_PATTERN.findall(content)
    except Exception:
        return []


def _find_tag_line_position(file_path: str) -> int | None:
    """Find the 0-indexed position of the first tag line in a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None

    # Find frontmatter end
    fm_end = None
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i
                break

    start = (fm_end + 1) if fm_end is not None else 0
    for i in range(start, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        if TAG_LINE_START.match(line):
            return i
    return None


def detect_tag_prefixes(vault_path: str) -> list[str]:
    """
    Scan all .md files and detect which tag prefixes are used.
    Returns sorted list of prefixes ordered by frequency (most common first).
    """
    prefix_counter: Counter = Counter()
    for md_file in _find_all_md_files(vault_path):
        tags = _extract_prefixed_tags(md_file)
        for prefix, _ in tags:
            prefix_counter[prefix.lower()] += 1

    # Return sorted by frequency (descending)
    return [prefix for prefix, _ in prefix_counter.most_common()]


def detect_note_directories(vault_path: str) -> list[dict]:
    """
    Detect directories that contain note files suitable for tagging.

    Heuristic:
    - Find all directories containing .md files with frontmatter
    - Group by the "nearest meaningful parent" (2 levels below vault root)
    - Assign labels from directory names

    Returns list of {"path": relative_path, "label": label, "content_strategy": strategy}
    """
    dir_file_counts: Counter = Counter()
    dir_has_frontmatter: dict[str, bool] = {}

    for md_file in _find_all_md_files(vault_path):
        rel_path = os.path.relpath(md_file, vault_path)
        parts = rel_path.split(os.sep)

        # Use 2-level grouping: "TopLevel/SubLevel" as the directory key
        if len(parts) >= 3:
            dir_key = os.path.join(parts[0], parts[1])
        elif len(parts) >= 2:
            dir_key = parts[0]
        else:
            dir_key = "."

        dir_file_counts[dir_key] += 1

        if _has_frontmatter(md_file):
            dir_has_frontmatter[dir_key] = True

    # Filter: only directories with frontmatter notes
    result = []
    for dir_key, count in dir_file_counts.most_common():
        if count < MIN_NOTES_PER_DIR:
            continue
        if not dir_has_frontmatter.get(dir_key, False):
            continue

        # Generate label from directory name
        label = dir_key.split(os.sep)[-1].lower().replace(" ", "_")
        # Remove common prefixes like numbers: "10. Literature" -> "literature"
        label = re.sub(r"^\d+\.\s*", "", label)
        if not label:
            label = "default"

        # Default strategy: body_text
        result.append({
            "path": dir_key,
            "label": label,
            "content_strategy": "body_text",
        })

    return result


def detect_taxonomy_source(vault_path: str, prefixes: list[str]) -> str:
    """
    Find the directory with the highest density of prefixed tags.
    This is likely where the "canonical" tagged notes live.

    Returns relative path to vault, or empty string if nothing found.
    """
    if not prefixes:
        return ""

    dir_tag_counts: Counter = Counter()

    for md_file in _find_all_md_files(vault_path):
        tags = _extract_prefixed_tags(md_file)
        matching_tags = [t for t in tags if t[0].lower() in prefixes]
        if matching_tags:
            rel_path = os.path.relpath(md_file, vault_path)
            parts = rel_path.split(os.sep)
            # Use parent directory of the file
            if len(parts) >= 2:
                parent = os.path.join(*parts[:-1])
            else:
                parent = "."
            dir_tag_counts[parent] += len(matching_tags)

    if not dir_tag_counts:
        return ""

    # Return the directory with the most tags
    best_dir, _ = dir_tag_counts.most_common(1)[0]
    return best_dir


def detect_tag_line_fallbacks(
    vault_path: str, note_dirs: list[dict]
) -> dict[str, int]:
    """
    For each note directory label, detect the most common tag line position.
    Returns {"label": position} mapping.
    """
    label_positions: dict[str, list[int]] = {}

    for nd in note_dirs:
        label = nd["label"]
        target = os.path.join(vault_path, nd["path"])
        if not os.path.isdir(target):
            continue

        positions = []
        for root, _, files in os.walk(target):
            for f in sorted(files):
                if not f.endswith(".md"):
                    continue
                pos = _find_tag_line_position(os.path.join(root, f))
                if pos is not None:
                    positions.append(pos)

        if positions:
            label_positions[label] = positions

    # For each label, use the most common (mode) position
    fallbacks = {}
    for label, positions in label_positions.items():
        counter = Counter(positions)
        fallbacks[label] = counter.most_common(1)[0][0]

    return fallbacks


def scan_vault(vault_path: str) -> dict:
    """
    Full vault scan: detect structure and produce a config dict.

    This is the main function called by `init` command.
    """
    config = default_config(vault_path)

    # Step 1: Detect tag prefixes
    prefixes = detect_tag_prefixes(vault_path)
    config["tag_prefixes"] = prefixes

    # Step 2: Detect note directories
    note_dirs = detect_note_directories(vault_path)
    config["note_directories"] = note_dirs

    # Step 3: Detect taxonomy source
    taxonomy_source = detect_taxonomy_source(vault_path, prefixes)
    config["taxonomy_source"] = taxonomy_source

    # Step 4: Detect tag line fallbacks
    fallbacks = detect_tag_line_fallbacks(vault_path, note_dirs)
    config["tag_line_fallbacks"] = fallbacks

    return config
