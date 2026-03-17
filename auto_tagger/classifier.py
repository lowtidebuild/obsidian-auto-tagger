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
                topics.append(t)

            for t in raw_themes:
                if t.startswith("[NEW]"):
                    has_new = True
                    t = t.replace("[NEW]", "")
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
