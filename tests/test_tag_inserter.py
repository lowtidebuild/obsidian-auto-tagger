import os
import tempfile
import shutil
import pytest
from auto_tagger.tag_inserter import insert_tags


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


def _make_note(tmp_dir, filename, content):
    path = os.path.join(tmp_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


STANDARD_NOTE = """---
title: "Test Note"
source: "NotebookLM"
type: article
created: 2024-03-01
updated: 2024-03-01
author: "Author"
---

#NotebookLM #TestTag #article

## Summary
Some content here.

## Keywords
test, example
"""


class TestInsertTags:
    def test_normal_insert(self, tmp_dir):
        path = _make_note(tmp_dir, "test.md", STANDARD_NOTE)
        result = insert_tags(path, tag_line_num=9, topics=["Law", "AI"], themes=["LegalTech"])
        assert result["written"] is True
        assert "#topic/Law" in result["after"]
        assert "#topic/AI" in result["after"]
        assert "#theme/LegalTech" in result["after"]
        # Original tags preserved
        assert "#NotebookLM" in result["after"]
        assert "#TestTag" in result["after"]
        # Verify file actually changed
        with open(path, "r") as f:
            content = f.read()
        assert "#topic/Law" in content

    def test_idempotency(self, tmp_dir):
        """Running insert twice should not duplicate tags."""
        path = _make_note(tmp_dir, "test.md", STANDARD_NOTE)
        insert_tags(path, tag_line_num=9, topics=["Law"], themes=["LegalTech"])
        # Second run with same tags
        result = insert_tags(path, tag_line_num=9, topics=["Law"], themes=["LegalTech"])
        with open(path, "r") as f:
            content = f.read()
        assert content.count("#topic/Law") == 1
        assert content.count("#theme/LegalTech") == 1

    def test_line_count_preserved(self, tmp_dir):
        path = _make_note(tmp_dir, "test.md", STANDARD_NOTE)
        with open(path, "r") as f:
            original_lines = len(f.readlines())
        insert_tags(path, tag_line_num=9, topics=["Law"], themes=["LegalTech"])
        with open(path, "r") as f:
            new_lines = len(f.readlines())
        assert new_lines == original_lines

    def test_dry_run_no_modification(self, tmp_dir):
        path = _make_note(tmp_dir, "test.md", STANDARD_NOTE)
        with open(path, "r") as f:
            original_content = f.read()
        result = insert_tags(
            path, tag_line_num=9, topics=["Law"], themes=["LegalTech"], dry_run=True
        )
        assert result["written"] is False
        assert "#topic/Law" in result["after"]
        # File unchanged
        with open(path, "r") as f:
            assert f.read() == original_content

    def test_empty_tags_no_modification(self, tmp_dir):
        path = _make_note(tmp_dir, "test.md", STANDARD_NOTE)
        with open(path, "r") as f:
            original_content = f.read()
        result = insert_tags(path, tag_line_num=9, topics=[], themes=[])
        assert result["written"] is False
        with open(path, "r") as f:
            assert f.read() == original_content

    def test_same_line_append(self, tmp_dir):
        """Tags should be appended on the same line, not a new line."""
        path = _make_note(tmp_dir, "test.md", STANDARD_NOTE)
        insert_tags(path, tag_line_num=9, topics=["Law"], themes=["LegalTech"])
        with open(path, "r") as f:
            lines = f.readlines()
        tag_line = lines[9]
        # All tags on one line
        assert "#NotebookLM" in tag_line
        assert "#topic/Law" in tag_line
        assert "#theme/LegalTech" in tag_line
        # No newline between original and new tags (single line)
        assert tag_line.count("\n") <= 1  # only trailing newline
