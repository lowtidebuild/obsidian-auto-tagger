"""Parse Obsidian .md notes: detect tag lines, extract content for classification."""

import os
import re
from dataclasses import dataclass

# Fallback tag line positions (0-indexed)
FALLBACK_TAG_LINE = {
    "literature": 9,
    "inbox": 8,
    "resources": 5,
}

# Tag pattern: #word (no space after #, not a heading)
# Matches: #NotebookLM, #topic/AI, #LegalQuants
# Does NOT match: # Heading, ## Subheading
INLINE_TAG_PATTERN = re.compile(r"#[A-Za-z\uAC00-\uD7A3][A-Za-z0-9\uAC00-\uD7A3_/]*")

# Pattern to identify a line that is a tag line (starts with #tag, not # heading)
TAG_LINE_START = re.compile(r"^#[^\s#]")

# Embed pattern
EMBED_PATTERN = re.compile(r"!\[\[.*?\]\]")

# Content cap for long notes
CONTENT_MAX_CHARS = 2000


@dataclass
class ParsedNote:
    file_path: str
    tag_line_num: int  # 0-indexed
    existing_tags: list[str]
    has_topic_theme: bool
    title: str
    content_for_classification: str
    source_folder: str  # "literature" | "inbox" | "resources"
    label: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = self.source_folder


def _find_frontmatter_end(lines: list[str]) -> int | None:
    """
    Find the line index of the closing --- of YAML frontmatter.
    Returns None if no frontmatter found.
    """
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i
    return None


def _detect_tag_line_by_pattern(lines: list[str], frontmatter_end: int | None) -> int | None:
    """
    Find the first tag line after frontmatter using pattern matching.
    A tag line starts with # followed by non-whitespace (not a Markdown heading).
    """
    start = (frontmatter_end + 1) if frontmatter_end is not None else 0
    for i in range(start, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        if TAG_LINE_START.match(line):
            return i
    return None


def _detect_tag_line(lines: list[str], source_folder: str) -> int:
    """
    Hybrid tag line detection:
    1. Pattern-based: find first #tag line after frontmatter
    2. Fallback: folder-specific fixed position
    """
    frontmatter_end = _find_frontmatter_end(lines)

    # Try pattern-based detection
    tag_line = _detect_tag_line_by_pattern(lines, frontmatter_end)
    if tag_line is not None:
        return tag_line

    # Fallback to fixed position
    fallback = FALLBACK_TAG_LINE.get(source_folder, 0)
    if fallback < len(lines):
        return fallback

    return 0


def _extract_tags(line: str) -> list[str]:
    """Extract all #tags from a single line."""
    return INLINE_TAG_PATTERN.findall(line)


def _has_topic_or_theme(tags: list[str]) -> bool:
    """Check if any tag starts with #topic/ or #theme/."""
    return any(t.startswith("#topic/") or t.startswith("#theme/") for t in tags)


def _extract_title(lines: list[str]) -> str:
    """Extract title from frontmatter or first heading."""
    for line in lines:
        if line.strip().startswith("title:"):
            # Remove 'title:' and surrounding quotes
            title = line.split(":", 1)[1].strip().strip('"').strip("'")
            return title
    # Fallback: first heading
    for line in lines:
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _extract_content_literature(lines: list[str], tag_line_num: int) -> str:
    """
    Extract classification content from Literature NotebookLM notes.
    Uses title + summary + keywords sections.
    """
    parts = []
    after_tag = lines[tag_line_num + 1:] if tag_line_num + 1 < len(lines) else []
    for line in after_tag:
        stripped = line.strip()
        # Skip section headers but include their content
        if stripped.startswith("## ") or stripped.startswith("# "):
            continue
        if stripped:
            parts.append(stripped)
    content = "\n".join(parts)
    return content[:CONTENT_MAX_CHARS]


def _extract_content_inbox(lines: list[str], tag_line_num: int) -> str:
    """
    Extract classification content from Inbox notes.
    Uses first 2000 chars of body text after tag line.
    """
    after_tag = lines[tag_line_num + 1:] if tag_line_num + 1 < len(lines) else []
    content = "\n".join(after_tag)
    return content[:CONTENT_MAX_CHARS]


def _extract_content_resources(lines: list[str], tag_line_num: int) -> str:
    """
    Extract classification content from Resources notes.
    Returns body text after tag line, excluding embed-only lines.
    """
    after_tag = lines[tag_line_num + 1:] if tag_line_num + 1 < len(lines) else []
    non_embed_parts = []
    for line in after_tag:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            continue
        if EMBED_PATTERN.fullmatch(stripped):
            continue
        non_embed_parts.append(stripped)
    return "\n".join(non_embed_parts)[:CONTENT_MAX_CHARS]


def is_embed_only(file_path: str) -> bool:
    """
    Check if a note is embed-only (no substantial text content after tag line).
    A note is embed-only if all non-empty lines after the tag line are
    embeds (![[...]]) or section headers, with less than 50 chars of real text.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Detect tag line
    tag_line_num = _detect_tag_line(lines, "resources")
    after_tag = lines[tag_line_num + 1:] if tag_line_num + 1 < len(lines) else []

    real_text = []
    for line in after_tag:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## ") or stripped.startswith("# "):
            continue
        if EMBED_PATTERN.fullmatch(stripped):
            continue
        real_text.append(stripped)

    total_real = "".join(real_text)
    return len(total_real) < 50


def parse_note(file_path: str, source_folder: str) -> ParsedNote:
    """
    Parse a single .md file.

    Args:
        file_path: Absolute path to .md file.
        source_folder: "literature", "inbox", or "resources".

    Returns:
        ParsedNote with all fields populated.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Strip newlines for processing but keep originals for line counting
    stripped_lines = [l.rstrip("\n") for l in lines]

    tag_line_num = _detect_tag_line(stripped_lines, source_folder)
    tag_line = stripped_lines[tag_line_num] if tag_line_num < len(stripped_lines) else ""
    existing_tags = _extract_tags(tag_line)
    has_topic_theme = _has_topic_or_theme(existing_tags)
    title = _extract_title(stripped_lines)

    # Extract content based on source folder
    if source_folder == "literature":
        content = _extract_content_literature(stripped_lines, tag_line_num)
    elif source_folder == "inbox":
        content = _extract_content_inbox(stripped_lines, tag_line_num)
    elif source_folder == "resources":
        content = _extract_content_resources(stripped_lines, tag_line_num)
    else:
        content = ""

    # Prepend title to content for classification
    if title and title.lower() not in content.lower():
        content = f"Title: {title}\n{content}"

    return ParsedNote(
        file_path=file_path,
        tag_line_num=tag_line_num,
        existing_tags=existing_tags,
        has_topic_theme=has_topic_theme,
        title=title,
        content_for_classification=content,
        source_folder=source_folder,
    )


def _detect_source_folder(file_path: str) -> str:
    """Infer source_folder from file path."""
    if "10. Literature" in file_path:
        return "literature"
    elif "00. Inbox" in file_path:
        return "inbox"
    elif "3. Resources" in file_path:
        return "resources"
    return "literature"  # default fallback


def collect_notes(vault_path: str, sub_path: str | None = None) -> list[ParsedNote]:
    """
    Collect all NotebookLM notes from the vault.

    Args:
        vault_path: Vault root path.
        sub_path: Optional subfolder to limit scope (relative to vault root).

    Returns:
        List of ParsedNote (includes both tagged and untagged).
    """
    notes = []

    if sub_path:
        # Specific subfolder only
        target = os.path.join(vault_path, sub_path)
        if not os.path.isdir(target):
            return []
        source_folder = _detect_source_folder(target)
        for root, _, files in os.walk(target):
            for f in sorted(files):
                if f.endswith(".md"):
                    full_path = os.path.join(root, f)
                    try:
                        note = parse_note(full_path, source_folder)
                        notes.append(note)
                    except Exception:
                        continue
    else:
        # All three NotebookLM directories
        dirs = [
            ("10. Literature/NotebookLM", "literature"),
            ("00. Inbox/NotebookLM", "inbox"),
            ("3. Resources/NotebookLM", "resources"),
        ]
        for subdir, source in dirs:
            target = os.path.join(vault_path, subdir)
            if not os.path.isdir(target):
                continue
            for root, _, files in os.walk(target):
                for f in sorted(files):
                    if f.endswith(".md"):
                        full_path = os.path.join(root, f)
                        try:
                            note = parse_note(full_path, source)
                            notes.append(note)
                        except Exception:
                            continue

    return notes


def _extract_content(
    lines: list[str],
    tag_line_num: int,
    strategy: str = "body_text",
    max_chars: int = CONTENT_MAX_CHARS,
) -> str:
    """Unified content extraction. Strategies: 'structured' (skip headers), 'body_text' (raw text)."""
    after_tag = lines[tag_line_num + 1:] if tag_line_num + 1 < len(lines) else []
    parts = []
    for line in after_tag:
        stripped = line.strip()
        if not stripped:
            if strategy == "body_text":
                parts.append("")
            continue
        if stripped.startswith("## ") or stripped.startswith("# "):
            if strategy == "structured":
                continue
            else:
                parts.append(stripped)
                continue
        if EMBED_PATTERN.fullmatch(stripped):
            continue
        parts.append(stripped)
    content = "\n".join(parts)
    return content[:max_chars]


def _has_prefixed_tags(tags: list[str], prefixes: list[str]) -> bool:
    """Check if any tag starts with any of the given prefixes."""
    for tag in tags:
        for prefix in prefixes:
            if tag.startswith(f"#{prefix}/"):
                return True
    return False


def parse_note_with_config(
    file_path: str, label: str, content_strategy: str, config: dict,
) -> ParsedNote:
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    stripped_lines = [l.rstrip("\n") for l in lines]
    prefixes = config.get("tag_prefixes", ["topic", "theme"])
    fallbacks = config.get("tag_line_fallbacks", {})

    frontmatter_end = _find_frontmatter_end(stripped_lines)
    tag_line_num = _detect_tag_line_by_pattern(stripped_lines, frontmatter_end)
    if tag_line_num is None:
        tag_line_num = fallbacks.get(label, 0)
        if tag_line_num >= len(stripped_lines):
            tag_line_num = 0

    tag_line = stripped_lines[tag_line_num] if tag_line_num < len(stripped_lines) else ""
    existing_tags = _extract_tags(tag_line)
    has_topic_theme = _has_prefixed_tags(existing_tags, prefixes)
    title = _extract_title(stripped_lines)

    max_chars = config.get("content_max_chars", CONTENT_MAX_CHARS)
    content = _extract_content(stripped_lines, tag_line_num, content_strategy, max_chars)

    if title and title.lower() not in content.lower():
        content = f"Title: {title}\n{content}"

    return ParsedNote(
        file_path=file_path, tag_line_num=tag_line_num,
        existing_tags=existing_tags, has_topic_theme=has_topic_theme,
        title=title, content_for_classification=content,
        source_folder=label, label=label,
    )


def collect_notes_with_config(config: dict, sub_path: str | None = None) -> list[ParsedNote]:
    vault_path = config["vault_path"]
    notes = []
    if sub_path:
        target = os.path.join(vault_path, sub_path)
        if not os.path.isdir(target):
            return []
        label = "default"
        strategy = "body_text"
        for nd in config.get("note_directories", []):
            if nd["path"] in sub_path:
                label = nd.get("label", "default")
                strategy = nd.get("content_strategy", "body_text")
                break
        for root, _, files in os.walk(target):
            for f in sorted(files):
                if f.endswith(".md"):
                    full_path = os.path.join(root, f)
                    try:
                        note = parse_note_with_config(full_path, label, strategy, config)
                        notes.append(note)
                    except Exception:
                        continue
    else:
        for nd in config.get("note_directories", []):
            target = os.path.join(vault_path, nd["path"])
            if not os.path.isdir(target):
                continue
            label = nd.get("label", "default")
            strategy = nd.get("content_strategy", "body_text")
            for root, _, files in os.walk(target):
                for f in sorted(files):
                    if f.endswith(".md"):
                        full_path = os.path.join(root, f)
                        try:
                            note = parse_note_with_config(full_path, label, strategy, config)
                            notes.append(note)
                        except Exception:
                            continue
    return notes
