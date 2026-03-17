import os
import tempfile
import shutil
import pytest
from auto_tagger.note_parser import (
    ParsedNote, parse_note, collect_notes,
    parse_note_with_config, collect_notes_with_config, _extract_content,
)


@pytest.fixture
def fixtures_dir():
    return os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


class TestParseNoteLiterature:
    def test_standard_format(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "literature_standard.md")
        note = parse_note(path, source_folder="literature")
        assert note.file_path == path
        assert note.tag_line_num == 9  # 0-indexed, line 10
        assert "#NotebookLM" in note.existing_tags
        assert "#LegalQuants" in note.existing_tags
        assert "#article" in note.existing_tags
        assert note.has_topic_theme is False
        assert "origin story" in note.title.lower() or "legal quant" in note.title.lower()
        assert len(note.content_for_classification) > 0
        assert note.source_folder == "literature"

    def test_already_tagged(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "literature_tagged.md")
        note = parse_note(path, source_folder="literature")
        assert note.has_topic_theme is True
        assert "#topic/AI" in note.existing_tags or "topic/AI" in str(note.existing_tags)

    def test_content_includes_title_summary_keywords(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "literature_standard.md")
        note = parse_note(path, source_folder="literature")
        content = note.content_for_classification.lower()
        # Should contain title, summary text, and keywords
        assert "legal" in content
        assert "quantitative" in content or "legal technology" in content


class TestParseNoteInbox:
    def test_long_format(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "inbox_long.md")
        note = parse_note(path, source_folder="inbox")
        assert note.tag_line_num == 8  # 0-indexed, line 9
        assert "#NotebookLM" in note.existing_tags
        assert note.has_topic_theme is False
        # Content should be capped at ~2000 chars
        assert len(note.content_for_classification) <= 2200
        assert len(note.content_for_classification) > 100


class TestParseNoteResources:
    def test_content_note(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "resources_content.md")
        note = parse_note(path, source_folder="resources")
        assert note.tag_line_num == 7  # 0-indexed, pattern-detected after frontmatter
        assert note.has_topic_theme is False
        assert len(note.content_for_classification) > 50

    def test_embed_only_note(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "resources_embed.md")
        note = parse_note(path, source_folder="resources")
        assert note.has_topic_theme is False
        # Embed-only: after removing embeds, only title remains in content
        content_without_title = note.content_for_classification.replace(f"Title: {note.title}", "").strip()
        assert content_without_title == ""

    def test_is_embed_only(self, fixtures_dir):
        from auto_tagger.note_parser import is_embed_only
        embed_path = os.path.join(fixtures_dir, "resources_embed.md")
        content_path = os.path.join(fixtures_dir, "resources_content.md")
        assert is_embed_only(embed_path) is True
        assert is_embed_only(content_path) is False


class TestParseNoteMalformed:
    def test_no_frontmatter_uses_fallback(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "malformed.md")
        # Pattern detection fails (no frontmatter), fallback to line 0 since #tag is first line
        note = parse_note(path, source_folder="literature")
        assert note.tag_line_num == 0
        assert "#NotebookLM" in note.existing_tags


class TestTagLineDetection:
    def test_pattern_detects_tag_line(self, fixtures_dir):
        """Pattern-based detection should find the tag line after frontmatter."""
        path = os.path.join(fixtures_dir, "literature_standard.md")
        note = parse_note(path, source_folder="literature")
        assert note.tag_line_num == 9

    def test_heading_not_confused_with_tags(self, tmp_dir):
        """# Heading (with space) should NOT be detected as tag line."""
        note_path = os.path.join(tmp_dir, "heading_note.md")
        with open(note_path, "w") as f:
            f.write("""---
title: "Test"
---

# This is a heading

#NotebookLM #TestTag

Content here.
""")
        note = parse_note(note_path, source_folder="literature")
        # Should find the #NotebookLM line, not the # heading
        assert "#NotebookLM" in note.existing_tags
        assert note.tag_line_num == 6  # 0-indexed


class TestCollectNotes:
    def test_collect_from_vault(self, tmp_dir, fixtures_dir):
        """Set up a mini vault and collect notes."""
        lit_dir = os.path.join(tmp_dir, "10. Literature", "NotebookLM", "LegalQuants")
        os.makedirs(lit_dir)
        shutil.copy(
            os.path.join(fixtures_dir, "literature_standard.md"),
            os.path.join(lit_dir, "note1.md"),
        )
        shutil.copy(
            os.path.join(fixtures_dir, "literature_tagged.md"),
            os.path.join(lit_dir, "note2.md"),
        )
        notes = collect_notes(tmp_dir)
        assert len(notes) == 2
        tagged = [n for n in notes if n.has_topic_theme]
        untagged = [n for n in notes if not n.has_topic_theme]
        assert len(tagged) == 1
        assert len(untagged) == 1

    def test_collect_with_subpath(self, tmp_dir, fixtures_dir):
        """--path flag should limit collection to specific subfolder."""
        lit_dir = os.path.join(tmp_dir, "10. Literature", "NotebookLM", "LegalQuants")
        inbox_dir = os.path.join(tmp_dir, "00. Inbox", "NotebookLM", "WorldAhead")
        os.makedirs(lit_dir)
        os.makedirs(inbox_dir)
        shutil.copy(
            os.path.join(fixtures_dir, "literature_standard.md"),
            os.path.join(lit_dir, "note1.md"),
        )
        shutil.copy(
            os.path.join(fixtures_dir, "inbox_long.md"),
            os.path.join(inbox_dir, "note2.md"),
        )
        notes = collect_notes(tmp_dir, sub_path="10. Literature/NotebookLM/LegalQuants")
        assert len(notes) == 1
        assert "note1.md" in notes[0].file_path


class TestExtractContentUnified:
    def test_structured_strategy(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "literature_standard.md")
        with open(path, "r") as f:
            lines = [l.rstrip("\n") for l in f.readlines()]
        content = _extract_content(lines, tag_line_num=9, strategy="structured")
        assert "quantitative" in content.lower() or "legal technology" in content.lower()
        assert "## Summary" not in content
        assert "## Keywords" not in content

    def test_body_text_strategy(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "inbox_long.md")
        with open(path, "r") as f:
            lines = [l.rstrip("\n") for l in f.readlines()]
        content = _extract_content(lines, tag_line_num=8, strategy="body_text")
        assert "geopolitical" in content.lower()
        assert len(content) <= 2200

    def test_content_max_chars(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "inbox_long.md")
        with open(path, "r") as f:
            lines = [l.rstrip("\n") for l in f.readlines()]
        content = _extract_content(lines, tag_line_num=8, strategy="body_text", max_chars=100)
        assert len(content) <= 150


class TestParseNoteWithConfig:
    def test_standard_with_config(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "literature_standard.md")
        config = {"tag_prefixes": ["topic", "theme"], "tag_line_fallbacks": {"literature": 9}}
        note = parse_note_with_config(path, label="literature", content_strategy="structured", config=config)
        assert note.file_path == path
        assert note.tag_line_num == 9
        assert note.has_topic_theme is False
        assert note.label == "literature"

    def test_custom_prefix_detection(self, fixtures_dir):
        path = os.path.join(fixtures_dir, "custom_tags_note.md")
        config = {"tag_prefixes": ["category", "subject"], "tag_line_fallbacks": {}}
        note = parse_note_with_config(path, label="articles", content_strategy="body_text", config=config)
        assert note.has_topic_theme is True
        assert "#category/Philosophy" in note.existing_tags


class TestCollectNotesWithConfig:
    def test_config_driven_collection(self, tmp_dir, fixtures_dir):
        lit_dir = os.path.join(tmp_dir, "MyNotes", "Articles")
        os.makedirs(lit_dir)
        shutil.copy(os.path.join(fixtures_dir, "literature_standard.md"), os.path.join(lit_dir, "note1.md"))
        config = {
            "vault_path": tmp_dir,
            "tag_prefixes": ["topic", "theme"],
            "note_directories": [{"path": "MyNotes/Articles", "label": "articles", "content_strategy": "structured"}],
            "tag_line_fallbacks": {"articles": 9},
        }
        notes = collect_notes_with_config(config)
        assert len(notes) == 1
        assert notes[0].label == "articles"
