from dataclasses import dataclass
from auto_tagger.classifier import _parse_response, _build_user_message, _build_system_prompt


@dataclass
class MockNote:
    file_path: str
    content_for_classification: str
    title: str = ""


class TestParseResponse:
    def _make_notes(self, count):
        return [MockNote(file_path=f"/note{i}.md", content_for_classification=f"content {i}") for i in range(1, count + 1)]

    def test_valid_json(self):
        notes = self._make_notes(2)
        response = '[{"id": 1, "topics": ["Law", "AI"], "themes": ["LegalTech"]}, {"id": 2, "topics": ["Economics"], "themes": ["SupplyChain"]}]'
        successes, failures = _parse_response(response, notes)
        assert len(successes) == 2
        assert len(failures) == 0
        assert successes[0].file_path == "/note1.md"
        assert successes[0].topics == ["Law", "AI"]
        assert successes[0].themes == ["LegalTech"]
        assert successes[0].has_new_tags is False

    def test_invalid_json_all_fail(self):
        notes = self._make_notes(3)
        response = "This is not valid JSON at all"
        successes, failures = _parse_response(response, notes)
        assert len(successes) == 0
        assert len(failures) == 3

    def test_markdown_fenced_json(self):
        notes = self._make_notes(1)
        response = '```json\n[{"id": 1, "topics": ["AI"], "themes": ["Innovation"]}]\n```'
        successes, failures = _parse_response(response, notes)
        assert len(successes) == 1
        assert successes[0].topics == ["AI"]

    def test_new_tag_markers(self):
        notes = self._make_notes(1)
        response = '[{"id": 1, "topics": ["[NEW]QuantLaw"], "themes": ["LegalTech", "[NEW]StableCoin"]}]'
        successes, failures = _parse_response(response, notes)
        assert len(successes) == 1
        assert successes[0].has_new_tags is True
        assert successes[0].topics == ["QuantLaw"]
        assert successes[0].themes == ["LegalTech", "StableCoin"]

    def test_partial_results(self):
        """If some notes are missing from response, they are failures."""
        notes = self._make_notes(3)
        response = '[{"id": 1, "topics": ["AI"], "themes": ["Innovation"]}]'
        successes, failures = _parse_response(response, notes)
        assert len(successes) == 1
        assert len(failures) == 2
        assert "/note2.md" in failures
        assert "/note3.md" in failures

    def test_out_of_range_id_ignored(self):
        notes = self._make_notes(2)
        response = '[{"id": 1, "topics": ["AI"], "themes": ["X"]}, {"id": 99, "topics": ["Y"], "themes": ["Z"]}]'
        successes, failures = _parse_response(response, notes)
        assert len(successes) == 1
        assert len(failures) == 1  # note2 not matched


class TestBuildUserMessage:
    def test_single_note(self):
        notes = [MockNote(file_path="/a.md", content_for_classification="Hello world")]
        msg = _build_user_message(notes)
        assert "[1] Hello world" in msg
        assert "Classify these notes:" in msg

    def test_multiple_notes(self):
        notes = [
            MockNote(file_path="/a.md", content_for_classification="Content A"),
            MockNote(file_path="/b.md", content_for_classification="Content B"),
        ]
        msg = _build_user_message(notes)
        assert "[1] Content A" in msg
        assert "[2] Content B" in msg


class TestBuildSystemPrompt:
    def test_standard_topic_theme(self):
        taxonomy = {"topic": ["AI", "Law"], "theme": ["Innovation"]}
        prefixes = ["topic", "theme"]
        prompt = _build_system_prompt(taxonomy, prefixes)
        assert "AI, Law" in prompt
        assert "Innovation" in prompt
        assert "topic" in prompt.lower()
        assert "theme" in prompt.lower()

    def test_custom_prefixes(self):
        taxonomy = {"category": ["Philosophy"], "subject": ["Ethics", "Logic"]}
        prefixes = ["category", "subject"]
        prompt = _build_system_prompt(taxonomy, prefixes)
        assert "Philosophy" in prompt
        assert "Ethics, Logic" in prompt
        assert "category" in prompt.lower()
        assert "subject" in prompt.lower()

    def test_single_prefix(self):
        taxonomy = {"tag": ["AI", "Law", "Science"]}
        prefixes = ["tag"]
        prompt = _build_system_prompt(taxonomy, prefixes)
        assert "AI, Law, Science" in prompt


class TestParseResponseDynamic:
    def _make_notes(self, count):
        return [MockNote(file_path=f"/note{i}.md", content_for_classification=f"content {i}") for i in range(1, count + 1)]

    def test_custom_prefix_response(self):
        from auto_tagger.classifier import _parse_response_dynamic
        notes = self._make_notes(1)
        prefixes = ["category", "subject"]
        response = '[{"id": 1, "category": ["Philosophy"], "subject": ["Ethics"]}]'
        successes, failures = _parse_response_dynamic(response, notes, prefixes)
        assert len(successes) == 1
        assert successes[0].tags == {"category": ["Philosophy"], "subject": ["Ethics"]}
