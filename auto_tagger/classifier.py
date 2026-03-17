"""Claude API batch classifier for note tagging."""

import json
import re
import time
from dataclasses import dataclass

import anthropic

# Model mapping
MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-20250514",
}

SYSTEM_PROMPT = """You are a knowledge management assistant classifying notes into topic/theme tags.
Given notes (title, summary, keywords or body text), assign tags from the canonical vocabulary.
Use 2-4 topic tags and 2-4 theme tags per note.

Rules:
1. Prefer existing tags. Propose NEW tags only when no existing tag fits (mark with [NEW]).
2. Topics = broad disciplines (e.g. Economics, AI, Law). Themes = specific concepts/phenomena (e.g. SupplyChain, Inequality).
3. PascalCase format (topic/Economics, theme/SupplyChain).
4. Classify by meaning regardless of language (Korean/English).
5. Respond ONLY with a JSON array, no other text.

CANONICAL TOPICS: {topics}

CANONICAL THEMES: {themes}

Response format:
[
  {{"id": 1, "topics": ["Law", "AI"], "themes": ["LegalTech", "[NEW]LegalQuant"]}},
  ...
]"""


@dataclass
class ClassificationResult:
    file_path: str
    topics: list[str]
    themes: list[str]
    has_new_tags: bool


def _build_user_message(notes: list) -> str:
    """
    Build the user message for a batch of notes.
    Each note is a ParsedNote with content_for_classification and title.
    """
    parts = []
    for i, note in enumerate(notes, 1):
        parts.append(f"[{i}] {note.content_for_classification}")
    return "Classify these notes:\n\n" + "\n\n".join(parts)


def _parse_response(
    response_text: str, notes: list
) -> tuple[list[ClassificationResult], list[str]]:
    """
    Parse Claude's JSON response into ClassificationResults.

    Returns:
        (successful_results, failed_file_paths)
    """
    # Extract JSON from response (handle possible markdown fences)
    cleaned = response_text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        # Entire response unparseable — all files fail
        return [], [n.file_path for n in notes]

    successes = []
    failures = []
    parsed_ids = set()

    for item in items:
        try:
            idx = item["id"] - 1  # Convert 1-indexed to 0-indexed
            if idx < 0 or idx >= len(notes):
                continue
            parsed_ids.add(idx)

            raw_topics = item.get("topics", [])
            raw_themes = item.get("themes", [])

            # Process [NEW] markers
            has_new = False
            topics = []
            themes = []

            for t in raw_topics:
                if t.startswith("[NEW]"):
                    has_new = True
                    t = t.replace("[NEW]", "")
                if t not in topics:
                    topics.append(t)

            for t in raw_themes:
                if t.startswith("[NEW]"):
                    has_new = True
                    t = t.replace("[NEW]", "")
                if t not in themes:
                    themes.append(t)

            successes.append(ClassificationResult(
                file_path=notes[idx].file_path,
                topics=topics,
                themes=themes,
                has_new_tags=has_new,
            ))
        except (KeyError, IndexError, TypeError):
            continue

    # Files not in parsed results are failures
    for i, note in enumerate(notes):
        if i not in parsed_ids:
            failures.append(note.file_path)

    return successes, failures


def classify_batch(
    notes: list,
    taxonomy: dict,
    model: str = "haiku",
) -> tuple[list[ClassificationResult], list[str]]:
    """
    Classify a batch of notes via Claude API.

    Args:
        notes: List of ParsedNote objects.
        taxonomy: {"topics": [...], "themes": [...]}
        model: "haiku" or "sonnet"

    Returns:
        (successful ClassificationResults, failed file_paths)

    Raises:
        anthropic.RateLimitError: Caller handles backoff.
    """
    if not notes:
        return [], []

    client = anthropic.Anthropic()

    system = SYSTEM_PROMPT.format(
        topics=", ".join(taxonomy["topics"]),
        themes=", ".join(taxonomy["themes"]),
    )
    user_message = _build_user_message(notes)

    model_id = MODELS.get(model, MODELS["haiku"])

    message = client.messages.create(
        model=model_id,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )

    response_text = ""
    for block in message.content:
        if block.type == "text":
            response_text += block.text

    return _parse_response(response_text, notes)


def classify_with_retry(
    notes: list,
    taxonomy: dict,
    model: str = "haiku",
    max_retries: int = 3,
) -> tuple[list[ClassificationResult], list[str]]:
    """
    Classify with exponential backoff on rate limits.

    Returns:
        (successful ClassificationResults, failed file_paths)
    """
    backoff = 1.0

    for attempt in range(max_retries):
        try:
            return classify_batch(notes, taxonomy, model)
        except anthropic.RateLimitError:
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            else:
                return [], [n.file_path for n in notes]
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            else:
                return [], [n.file_path for n in notes]


# Dynamic system prompt template
SYSTEM_PROMPT_TEMPLATE = """You are a knowledge management assistant classifying notes into tagged categories.
Given notes (title, summary, keywords or body text), assign tags from the canonical vocabulary.
Use 2-4 tags per category per note.

Rules:
1. Prefer existing tags. Propose NEW tags only when no existing tag fits (mark with [NEW]).
2. {category_descriptions}
3. PascalCase format ({format_examples}).
4. Classify by meaning regardless of language (Korean/English).
5. Respond ONLY with a JSON array, no other text.

{canonical_lists}

Response format:
[
  {{"id": 1, {response_format}}},
  ...
]"""


def _build_system_prompt(taxonomy: dict, prefixes: list[str]) -> str:
    """Build a system prompt dynamically from taxonomy and prefix list."""
    if len(prefixes) == 2:
        desc = (f"{prefixes[0].capitalize()}s = broad disciplines/categories. "
                f"{prefixes[1].capitalize()}s = specific concepts/phenomena.")
    else:
        desc = ", ".join(f"{p.capitalize()}s" for p in prefixes) + " = classification categories."

    format_examples = ", ".join(f"{p}/Example" for p in prefixes)

    canonical_parts = []
    for prefix in prefixes:
        tags = taxonomy.get(prefix, [])
        canonical_parts.append(f"CANONICAL {prefix.upper()}S: {', '.join(tags)}")
    canonical_lists = "\n\n".join(canonical_parts)

    response_parts = [f'"{prefix}": ["Tag1", "Tag2"]' for prefix in prefixes]
    response_format = ", ".join(response_parts)

    return SYSTEM_PROMPT_TEMPLATE.format(
        category_descriptions=desc, format_examples=format_examples,
        canonical_lists=canonical_lists, response_format=response_format,
    )


@dataclass
class DynamicClassificationResult:
    file_path: str
    tags: dict[str, list[str]]  # {"prefix": ["Tag1", "Tag2"]}
    has_new_tags: bool


def _parse_response_dynamic(
    response_text: str, notes: list, prefixes: list[str]
) -> tuple[list[DynamicClassificationResult], list[str]]:
    """Parse Claude's response with dynamic prefix names."""
    cleaned = response_text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        return [], [n.file_path for n in notes]

    successes = []
    parsed_ids = set()

    for item in items:
        try:
            idx = item["id"] - 1
            if idx < 0 or idx >= len(notes):
                continue
            parsed_ids.add(idx)

            has_new = False
            tags: dict[str, list[str]] = {}

            for prefix in prefixes:
                raw_values = item.get(prefix, [])
                cleaned_values = []
                seen = set()
                for v in raw_values:
                    if v.startswith("[NEW]"):
                        has_new = True
                        v = v.replace("[NEW]", "")
                    if v not in seen:
                        cleaned_values.append(v)
                        seen.add(v)
                tags[prefix] = cleaned_values

            successes.append(DynamicClassificationResult(
                file_path=notes[idx].file_path, tags=tags, has_new_tags=has_new,
            ))
        except (KeyError, IndexError, TypeError):
            continue

    failures = [notes[i].file_path for i in range(len(notes)) if i not in parsed_ids]
    return successes, failures


def classify_batch_dynamic(
    notes: list, taxonomy: dict, prefixes: list[str], model: str = "haiku",
) -> tuple[list[DynamicClassificationResult], list[str]]:
    if not notes:
        return [], []
    client = anthropic.Anthropic()
    system = _build_system_prompt(taxonomy, prefixes)
    user_message = _build_user_message(notes)
    model_id = MODELS.get(model, MODELS["haiku"])
    message = client.messages.create(
        model=model_id, max_tokens=2048, system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    response_text = ""
    for block in message.content:
        if block.type == "text":
            response_text += block.text
    return _parse_response_dynamic(response_text, notes, prefixes)


def classify_with_retry_dynamic(
    notes: list, taxonomy: dict, prefixes: list[str],
    model: str = "haiku", max_retries: int = 3,
) -> tuple[list[DynamicClassificationResult], list[str]]:
    backoff = 1.0
    for attempt in range(max_retries):
        try:
            return classify_batch_dynamic(notes, taxonomy, prefixes, model)
        except anthropic.RateLimitError:
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            else:
                return [], [n.file_path for n in notes]
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            else:
                return [], [n.file_path for n in notes]
