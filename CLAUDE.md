# Obsidian Auto-Tagger

Python CLI tool that applies topic/theme tags to Obsidian NotebookLM notes using Claude AI.

## Commands
- pytest tests/ -v  # Run all tests
- python -m auto_tagger --help  # CLI help
- python -m auto_tagger taxonomy  # Extract taxonomy
- python -m auto_tagger tag --dry-run  # Preview tagging

## Architecture
- auto_tagger/taxonomy.py: Tag extraction from reading notes
- auto_tagger/note_parser.py: Parse .md notes, detect tag lines
- auto_tagger/classifier.py: Claude API batch classification
- auto_tagger/tag_inserter.py: Idempotent tag insertion with atomic writes
- auto_tagger/progress.py: JSON-based progress tracking with resume

## Key invariants
- Tag insertion is idempotent (running twice produces same result)
- Atomic writes (tempfile + rename) prevent partial file corruption
- Line count must be preserved after tag insertion
- PascalCase normalization for all tags
