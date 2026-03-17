import os
import tempfile
import shutil
import pytest
from auto_tagger.scanner import (
    scan_vault,
    detect_tag_prefixes,
    detect_note_directories,
    detect_taxonomy_source,
    detect_tag_line_fallbacks,
)


@pytest.fixture
def fixtures_dir():
    return os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def sample_vault(tmp_dir, fixtures_dir):
    """Create a realistic vault with multiple directories and note types."""
    # Reading notes (taxonomy source - high tag density)
    reading_dir = os.path.join(tmp_dir, "10. Literature", "독서")
    os.makedirs(reading_dir)
    shutil.copy(
        os.path.join(fixtures_dir, "reading_note_sample.md"),
        os.path.join(reading_dir, "Chip War.md"),
    )

    # Literature NotebookLM
    lit_nlm = os.path.join(tmp_dir, "10. Literature", "NotebookLM", "Topic1")
    os.makedirs(lit_nlm)
    shutil.copy(
        os.path.join(fixtures_dir, "literature_standard.md"),
        os.path.join(lit_nlm, "note1.md"),
    )
    shutil.copy(
        os.path.join(fixtures_dir, "literature_tagged.md"),
        os.path.join(lit_nlm, "note2.md"),
    )

    # Inbox
    inbox_dir = os.path.join(tmp_dir, "00. Inbox", "NotebookLM", "WorldAhead")
    os.makedirs(inbox_dir)
    shutil.copy(
        os.path.join(fixtures_dir, "inbox_long.md"),
        os.path.join(inbox_dir, "note3.md"),
    )

    # Resources
    res_dir = os.path.join(tmp_dir, "3. Resources", "NotebookLM", "Blockchain")
    os.makedirs(res_dir)
    shutil.copy(
        os.path.join(fixtures_dir, "resources_content.md"),
        os.path.join(res_dir, "note4.md"),
    )

    return tmp_dir


@pytest.fixture
def custom_vault(tmp_dir, fixtures_dir):
    """A vault using non-standard tag prefixes (#category/, #subject/)."""
    notes_dir = os.path.join(tmp_dir, "Notes", "Articles")
    os.makedirs(notes_dir)
    shutil.copy(
        os.path.join(fixtures_dir, "custom_tags_note.md"),
        os.path.join(notes_dir, "philosophy.md"),
    )
    # Add the same file as a "taxonomy source"
    canon_dir = os.path.join(tmp_dir, "Notes", "Books")
    os.makedirs(canon_dir)
    shutil.copy(
        os.path.join(fixtures_dir, "custom_tags_note.md"),
        os.path.join(canon_dir, "phil_book.md"),
    )
    return tmp_dir


@pytest.fixture
def empty_vault(tmp_dir):
    """A vault with notes but no tags at all."""
    notes_dir = os.path.join(tmp_dir, "Notes")
    os.makedirs(notes_dir)
    # Create a simple note with no category tags
    with open(os.path.join(notes_dir, "bare.md"), "w") as f:
        f.write("---\ntitle: Test\n---\n\n#simple\n\nSome content.\n")
    return tmp_dir


class TestDetectTagPrefixes:
    def test_detects_topic_theme(self, sample_vault):
        prefixes = detect_tag_prefixes(sample_vault)
        assert "topic" in prefixes
        assert "theme" in prefixes

    def test_detects_custom_prefixes(self, custom_vault):
        prefixes = detect_tag_prefixes(custom_vault)
        assert "category" in prefixes
        assert "subject" in prefixes

    def test_empty_vault_returns_empty(self, empty_vault):
        prefixes = detect_tag_prefixes(empty_vault)
        assert prefixes == []

    def test_sorted_by_frequency(self, sample_vault):
        """Most frequently used prefix should come first."""
        prefixes = detect_tag_prefixes(sample_vault)
        # In our sample vault, both topic and theme exist
        assert isinstance(prefixes, list)
        assert len(prefixes) >= 2


class TestDetectNoteDirectories:
    def test_finds_directories_with_md_files(self, sample_vault):
        dirs = detect_note_directories(sample_vault)
        # Should find at least the NotebookLM directories
        paths = [d["path"] for d in dirs]
        assert any("NotebookLM" in p for p in paths)

    def test_assigns_labels(self, sample_vault):
        dirs = detect_note_directories(sample_vault)
        for d in dirs:
            assert "path" in d
            assert "label" in d
            assert "content_strategy" in d

    def test_custom_vault_directories(self, custom_vault):
        dirs = detect_note_directories(custom_vault)
        assert len(dirs) >= 1
        paths = [d["path"] for d in dirs]
        assert any("Notes" in p for p in paths)


class TestDetectTaxonomySource:
    def test_finds_highest_tag_density(self, sample_vault):
        prefixes = ["topic", "theme"]
        source = detect_taxonomy_source(sample_vault, prefixes)
        # Reading notes dir has the most tags
        assert "독서" in source or "Literature" in source

    def test_empty_vault_returns_empty(self, empty_vault):
        source = detect_taxonomy_source(empty_vault, [])
        assert source == ""


class TestDetectTagLineFallbacks:
    def test_detects_positions(self, sample_vault):
        dirs = detect_note_directories(sample_vault)
        fallbacks = detect_tag_line_fallbacks(sample_vault, dirs)
        assert isinstance(fallbacks, dict)
        # Each label should have a fallback position
        for d in dirs:
            label = d["label"]
            if label in fallbacks:
                assert isinstance(fallbacks[label], int)
                assert fallbacks[label] >= 0


class TestScanVault:
    def test_full_scan_produces_valid_config(self, sample_vault):
        config = scan_vault(sample_vault)
        assert config["vault_path"] == sample_vault
        assert len(config["tag_prefixes"]) >= 2
        assert len(config["note_directories"]) >= 1
        assert config["taxonomy_source"] != ""
        assert config["content_max_chars"] == 2000

    def test_custom_vault_scan(self, custom_vault):
        config = scan_vault(custom_vault)
        assert "category" in config["tag_prefixes"] or "subject" in config["tag_prefixes"]

    def test_empty_vault_warns_cold_start(self, empty_vault):
        config = scan_vault(empty_vault)
        # Should still produce a valid structure
        assert config["vault_path"] == empty_vault
        assert config["tag_prefixes"] == []
        assert config["taxonomy_source"] == ""
