import json
import os
import tempfile
import shutil
import pytest
from auto_tagger.taxonomy import (
    extract_tags_from_file,
    normalize_tag,
    extract_taxonomy,
    save_taxonomy,
    load_taxonomy,
    add_new_tags,
    extract_taxonomy_from_dir,
    extract_tags_with_prefixes,
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
    """Create a minimal vault structure with reading notes."""
    reading_dir = os.path.join(tmp_dir, "10. Literature", "독서")
    os.makedirs(reading_dir)
    shutil.copy(
        os.path.join(fixtures_dir, "reading_note_sample.md"),
        os.path.join(reading_dir, "Chip War.md"),
    )
    return tmp_dir


class TestNormalizeTag:
    def test_already_pascal(self):
        assert normalize_tag("Economics") == "Economics"

    def test_lowercase(self):
        assert normalize_tag("economics") == "Economics"

    def test_multi_word_with_spaces(self):
        assert normalize_tag("supply chain") == "SupplyChain"

    def test_already_pascal_multi(self):
        assert normalize_tag("SupplyChain") == "SupplyChain"

    def test_mixed_case(self):
        assert normalize_tag("usChinaRivalry") == "UsChinaRivalry"

    def test_single_char(self):
        assert normalize_tag("AI") == "AI"


class TestExtractTagsFromFile:
    def test_reading_note(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "reading_note_sample.md")
        topics, themes = extract_tags_from_file(path)
        assert set(topics) == {"Technology", "Geopolitics", "Economics"}
        assert set(themes) == {"Semiconductors", "SupplyChain", "USChinaRivalry", "Innovation"}

    def test_no_topic_theme_tags(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "literature_standard.md")
        topics, themes = extract_tags_from_file(path)
        assert topics == []
        assert themes == []


class TestExtractTaxonomy:
    def test_from_sample_vault(self, sample_vault):
        taxonomy = extract_taxonomy(sample_vault)
        assert "Technology" in taxonomy["topics"]
        assert "Geopolitics" in taxonomy["topics"]
        assert "Economics" in taxonomy["topics"]
        assert "Semiconductors" in taxonomy["themes"]
        assert "SupplyChain" in taxonomy["themes"]
        # Sorted alphabetically
        assert taxonomy["topics"] == sorted(taxonomy["topics"])
        assert taxonomy["themes"] == sorted(taxonomy["themes"])

    def test_empty_vault(self, tmp_dir):
        reading_dir = os.path.join(tmp_dir, "10. Literature", "독서")
        os.makedirs(reading_dir)
        taxonomy = extract_taxonomy(tmp_dir)
        assert taxonomy == {"topics": [], "themes": []}

    def test_no_reading_dir(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            extract_taxonomy(tmp_dir)

    def test_deduplication(self, tmp_dir):
        """Two notes with same tags should not produce duplicates."""
        reading_dir = os.path.join(tmp_dir, "10. Literature", "독서")
        os.makedirs(reading_dir)
        note_content = """---
title: "Test"
---

#book #topic/Economics #theme/Innovation

Content here.
"""
        for name in ["Note1.md", "Note2.md"]:
            with open(os.path.join(reading_dir, name), "w") as f:
                f.write(note_content)
        taxonomy = extract_taxonomy(tmp_dir)
        assert taxonomy["topics"].count("Economics") == 1
        assert taxonomy["themes"].count("Innovation") == 1


class TestSaveLoadTaxonomy:
    def test_roundtrip(self, tmp_dir):
        taxonomy = {"topics": ["AI", "Economics"], "themes": ["Innovation", "SupplyChain"]}
        path = os.path.join(tmp_dir, "taxonomy.json")
        save_taxonomy(taxonomy, path)
        loaded = load_taxonomy(path)
        assert loaded == taxonomy

    def test_load_missing_file(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            load_taxonomy(os.path.join(tmp_dir, "nonexistent.json"))


class TestAddNewTags:
    def test_add_new(self, tmp_dir):
        taxonomy = {"topics": ["AI"], "themes": ["Innovation"]}
        path = os.path.join(tmp_dir, "taxonomy.json")
        save_taxonomy(taxonomy, path)
        add_new_tags(path, new_topics=["Law"], new_themes=["LegalTech"])
        loaded = load_taxonomy(path)
        assert "Law" in loaded["topics"]
        assert "LegalTech" in loaded["themes"]
        # Still sorted
        assert loaded["topics"] == sorted(loaded["topics"])

    def test_add_duplicate_ignored(self, tmp_dir):
        taxonomy = {"topics": ["AI", "Law"], "themes": ["Innovation"]}
        path = os.path.join(tmp_dir, "taxonomy.json")
        save_taxonomy(taxonomy, path)
        add_new_tags(path, new_topics=["AI"], new_themes=["Innovation"])
        loaded = load_taxonomy(path)
        assert loaded["topics"].count("AI") == 1
        assert loaded["themes"].count("Innovation") == 1


class TestExtractTaxonomyFromDir:
    def test_from_explicit_directory(self, tmp_dir, fixtures_dir):
        custom_dir = os.path.join(tmp_dir, "my_books")
        os.makedirs(custom_dir)
        shutil.copy(
            os.path.join(fixtures_dir, "reading_note_sample.md"),
            os.path.join(custom_dir, "sample.md"),
        )
        taxonomy = extract_taxonomy_from_dir(custom_dir, prefixes=["topic", "theme"])
        assert "Technology" in taxonomy["topic"]
        assert "Semiconductors" in taxonomy["theme"]

    def test_custom_prefixes(self, tmp_dir, fixtures_dir):
        custom_dir = os.path.join(tmp_dir, "articles")
        os.makedirs(custom_dir)
        shutil.copy(
            os.path.join(fixtures_dir, "custom_tags_note.md"),
            os.path.join(custom_dir, "phil.md"),
        )
        taxonomy = extract_taxonomy_from_dir(custom_dir, prefixes=["category", "subject"])
        assert "Philosophy" in taxonomy["category"]
        assert "Consciousness" in taxonomy["subject"]

    def test_empty_directory(self, tmp_dir):
        os.makedirs(os.path.join(tmp_dir, "empty"))
        taxonomy = extract_taxonomy_from_dir(
            os.path.join(tmp_dir, "empty"), prefixes=["topic", "theme"]
        )
        assert taxonomy == {"topic": [], "theme": []}

    def test_nonexistent_directory(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            extract_taxonomy_from_dir(
                os.path.join(tmp_dir, "nope"), prefixes=["topic"]
            )


class TestExtractTagsWithPrefixes:
    def test_extracts_standard(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "reading_note_sample.md")
        result = extract_tags_with_prefixes(path, prefixes=["topic", "theme"])
        assert "Technology" in result["topic"]
        assert "Semiconductors" in result["theme"]

    def test_extracts_custom_prefixes(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "custom_tags_note.md")
        result = extract_tags_with_prefixes(path, prefixes=["category", "subject"])
        assert "Philosophy" in result["category"]
        assert "Consciousness" in result["subject"]
