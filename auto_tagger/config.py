"""Configuration loading, saving, and validation for universal tagger."""

import json
import os

VALID_CONTENT_STRATEGIES = {"structured", "body_text"}


class ConfigError(Exception):
    """Raised when config validation fails."""
    pass


def default_config(vault_path: str) -> dict:
    """Create a default (empty) config for a vault."""
    return {
        "vault_path": vault_path,
        "tag_prefixes": [],
        "note_directories": [],
        "taxonomy_source": "",
        "tag_line_fallbacks": {},
        "content_max_chars": 2000,
        "embed_only_threshold": 50,
        "model": "haiku",
        "batch_size": 10,
    }


def validate_config(config: dict) -> None:
    """
    Validate config structure. Raises ConfigError on problems.

    Required fields:
    - vault_path: non-empty string
    - tag_prefixes: non-empty list of strings
    - note_directories: non-empty list of dicts with path, label, content_strategy
    - taxonomy_source: string (key must exist)
    """
    if "vault_path" not in config or not config["vault_path"]:
        raise ConfigError("vault_path is required and must be non-empty")

    if "tag_prefixes" not in config or not config["tag_prefixes"]:
        raise ConfigError("tag_prefixes must be a non-empty list (e.g. ['topic', 'theme'])")

    if "note_directories" not in config or not config["note_directories"]:
        raise ConfigError("note_directories must be a non-empty list")

    for i, nd in enumerate(config["note_directories"]):
        if "path" not in nd:
            raise ConfigError(f"note_directories[{i}] missing 'path'")
        if "label" not in nd:
            raise ConfigError(f"note_directories[{i}] missing 'label'")
        strategy = nd.get("content_strategy", "body_text")
        if strategy not in VALID_CONTENT_STRATEGIES:
            raise ConfigError(
                f"note_directories[{i}] content_strategy must be one of "
                f"{VALID_CONTENT_STRATEGIES}, got '{strategy}'"
            )

    if "taxonomy_source" not in config:
        raise ConfigError("taxonomy_source key is required (can be empty string for cold start)")


def save_config(config: dict, path: str) -> None:
    """Save config dict to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_config(path: str) -> dict:
    """
    Load config from JSON file.

    Raises:
        FileNotFoundError: File does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_tag_prefixes(config: dict) -> list[str]:
    """Return the list of tag prefixes from config."""
    return config.get("tag_prefixes", [])


def get_note_dir_map(config: dict) -> dict[str, dict]:
    """
    Return a mapping from directory path to its metadata.
    {"10. Literature/NotebookLM": {"label": "literature", "content_strategy": "structured"}}
    """
    result = {}
    for nd in config.get("note_directories", []):
        result[nd["path"]] = {
            "label": nd.get("label", "default"),
            "content_strategy": nd.get("content_strategy", "body_text"),
        }
    return result


def get_label_for_path(config: dict, file_path: str) -> str:
    """
    Determine the label for a file path by matching against note_directories.
    Returns "default" if no match found.
    """
    for nd in config.get("note_directories", []):
        if nd["path"] in file_path:
            return nd.get("label", "default")
    return "default"
