"""Extract and manage the canonical tag taxonomy from reading notes."""

import json
import os
import re


# Hardcoded reading notes path relative to vault root
READING_NOTES_SUBDIR = os.path.join("10. Literature", "독서")

# Pattern to match #topic/... and #theme/... tags
TAG_PATTERN = re.compile(r"#(topic|theme)/(\S+)")

# Pattern to detect a tag line: starts with # followed by non-space (not a heading)
TAG_LINE_PATTERN = re.compile(r"^#[^\s#]")


def normalize_tag(tag: str) -> str:
    """
    Normalize a tag value to PascalCase.

    - "economics" -> "Economics"
    - "supply chain" -> "SupplyChain"
    - "AI" -> "AI" (preserved)
    - "USChinaRivalry" -> "USChinaRivalry" (preserved)
    """
    # If it contains spaces, split and capitalize each part
    if " " in tag:
        return "".join(word[0].upper() + word[1:] for word in tag.split() if word)

    # If all uppercase (like "AI"), preserve
    if tag.isupper():
        return tag

    # If already PascalCase (starts with upper, has mixed case), preserve
    if tag[0].isupper() and not tag.islower():
        return tag

    # Simple lowercase -> capitalize first letter
    return tag[0].upper() + tag[1:]


def extract_tags_from_file(file_path: str) -> tuple[list[str], list[str]]:
    """
    Extract #topic/... and #theme/... tags from a single .md file.

    Returns:
        (topics, themes) — lists of tag values (without prefix), normalized to PascalCase.
    """
    topics = []
    themes = []

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    for match in TAG_PATTERN.finditer(content):
        category, value = match.group(1), match.group(2)
        normalized = normalize_tag(value)
        if category == "topic":
            topics.append(normalized)
        elif category == "theme":
            themes.append(normalized)

    return topics, themes


def extract_taxonomy(vault_path: str) -> dict:
    """
    Extract taxonomy from all reading notes in the vault.

    Args:
        vault_path: Obsidian vault root path (the Zettelkasten directory).

    Returns:
        {"topics": [...], "themes": [...]} — sorted, deduplicated.

    Raises:
        FileNotFoundError: Reading notes directory does not exist.
    """
    reading_dir = os.path.join(vault_path, READING_NOTES_SUBDIR)
    if not os.path.isdir(reading_dir):
        raise FileNotFoundError(f"Reading notes directory not found: {reading_dir}")

    all_topics = set()
    all_themes = set()

    for filename in os.listdir(reading_dir):
        if not filename.endswith(".md"):
            continue
        file_path = os.path.join(reading_dir, filename)
        topics, themes = extract_tags_from_file(file_path)
        all_topics.update(topics)
        all_themes.update(themes)

    return {
        "topics": sorted(all_topics),
        "themes": sorted(all_themes),
    }


def save_taxonomy(taxonomy: dict, output_path: str) -> None:
    """Save taxonomy dict to JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(taxonomy, f, ensure_ascii=False, indent=2)


def load_taxonomy(path: str) -> dict:
    """
    Load taxonomy from JSON file.

    Raises:
        FileNotFoundError: File does not exist.
        json.JSONDecodeError: File is corrupted.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Taxonomy file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def add_new_tags(
    taxonomy_path: str,
    new_topics: list[str] | None = None,
    new_themes: list[str] | None = None,
) -> None:
    """
    Add new tags to existing taxonomy.json. Duplicates are ignored.
    Result is sorted alphabetically.
    """
    taxonomy = load_taxonomy(taxonomy_path)

    if new_topics:
        existing = set(taxonomy["topics"])
        for t in new_topics:
            normalized = normalize_tag(t)
            existing.add(normalized)
        taxonomy["topics"] = sorted(existing)

    if new_themes:
        existing = set(taxonomy["themes"])
        for t in new_themes:
            normalized = normalize_tag(t)
            existing.add(normalized)
        taxonomy["themes"] = sorted(existing)

    save_taxonomy(taxonomy, taxonomy_path)
