import json
import os
import tempfile
import shutil
import pytest
from auto_tagger.config import (
    load_config,
    save_config,
    validate_config,
    default_config,
    ConfigError,
)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def sample_config(tmp_dir):
    """A valid config dict for testing."""
    return {
        "vault_path": tmp_dir,
        "tag_prefixes": ["topic", "theme"],
        "note_directories": [
            {
                "path": "10. Literature/NotebookLM",
                "label": "literature",
                "content_strategy": "structured",
            }
        ],
        "taxonomy_source": "10. Literature/독서",
        "tag_line_fallbacks": {"literature": 9},
        "content_max_chars": 2000,
        "embed_only_threshold": 50,
        "model": "haiku",
        "batch_size": 10,
    }


class TestDefaultConfig:
    def test_creates_valid_structure(self):
        cfg = default_config("/some/vault")
        assert cfg["vault_path"] == "/some/vault"
        assert cfg["tag_prefixes"] == []
        assert cfg["note_directories"] == []
        assert cfg["taxonomy_source"] == ""
        assert cfg["content_max_chars"] == 2000
        assert cfg["embed_only_threshold"] == 50
        assert cfg["model"] == "haiku"
        assert cfg["batch_size"] == 10
        assert cfg["tag_line_fallbacks"] == {}


class TestValidateConfig:
    def test_valid_config_passes(self, sample_config):
        validate_config(sample_config)

    def test_missing_vault_path(self, sample_config):
        del sample_config["vault_path"]
        with pytest.raises(ConfigError, match="vault_path"):
            validate_config(sample_config)

    def test_empty_tag_prefixes(self, sample_config):
        sample_config["tag_prefixes"] = []
        with pytest.raises(ConfigError, match="tag_prefixes"):
            validate_config(sample_config)

    def test_empty_note_directories(self, sample_config):
        sample_config["note_directories"] = []
        with pytest.raises(ConfigError, match="note_directories"):
            validate_config(sample_config)

    def test_missing_directory_label(self, sample_config):
        sample_config["note_directories"][0].pop("label")
        with pytest.raises(ConfigError, match="label"):
            validate_config(sample_config)

    def test_invalid_content_strategy(self, sample_config):
        sample_config["note_directories"][0]["content_strategy"] = "invalid"
        with pytest.raises(ConfigError, match="content_strategy"):
            validate_config(sample_config)

    def test_missing_taxonomy_source(self, sample_config):
        del sample_config["taxonomy_source"]
        with pytest.raises(ConfigError, match="taxonomy_source"):
            validate_config(sample_config)


class TestSaveLoadConfig:
    def test_roundtrip(self, tmp_dir, sample_config):
        path = os.path.join(tmp_dir, "config.json")
        save_config(sample_config, path)
        loaded = load_config(path)
        assert loaded == sample_config

    def test_load_missing_file(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            load_config(os.path.join(tmp_dir, "nonexistent.json"))

    def test_save_creates_file(self, tmp_dir, sample_config):
        path = os.path.join(tmp_dir, "config.json")
        save_config(sample_config, path)
        assert os.path.exists(path)
        with open(path, "r") as f:
            data = json.load(f)
        assert data["vault_path"] == sample_config["vault_path"]

    def test_unicode_preserved(self, tmp_dir, sample_config):
        """Korean characters in taxonomy_source must survive roundtrip."""
        path = os.path.join(tmp_dir, "config.json")
        save_config(sample_config, path)
        loaded = load_config(path)
        assert loaded["taxonomy_source"] == "10. Literature/독서"


class TestConfigGetters:
    def test_get_tag_prefixes(self, sample_config):
        from auto_tagger.config import get_tag_prefixes
        assert get_tag_prefixes(sample_config) == ["topic", "theme"]

    def test_get_note_dirs(self, sample_config):
        from auto_tagger.config import get_note_dir_map
        dir_map = get_note_dir_map(sample_config)
        assert dir_map == {
            "10. Literature/NotebookLM": {
                "label": "literature",
                "content_strategy": "structured",
            }
        }

    def test_get_label_for_path(self, sample_config):
        from auto_tagger.config import get_label_for_path
        label = get_label_for_path(
            sample_config,
            "/vault/10. Literature/NotebookLM/subfolder/note.md",
        )
        assert label == "literature"

    def test_get_label_for_unknown_path(self, sample_config):
        from auto_tagger.config import get_label_for_path
        label = get_label_for_path(sample_config, "/vault/unknown/note.md")
        assert label == "default"
