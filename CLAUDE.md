# Obsidian Universal Tagger

Python CLI tool that applies configurable tags to ANY Obsidian vault notes using Claude AI.

## Commands
- pytest tests/ -v  # Run all tests
- python -m auto_tagger --help  # CLI help
- python -m auto_tagger init /path/to/vault  # Scan vault and generate config
- python -m auto_tagger taxonomy  # Extract taxonomy from config source
- python -m auto_tagger tag --dry-run  # Preview tagging
- python -m auto_tagger stats  # Show tagging statistics

## Architecture
- auto_tagger/config.py: Config loading/saving/validation
- auto_tagger/scanner.py: Vault structure auto-detection
- auto_tagger/taxonomy.py: Tag extraction from configured taxonomy source
- auto_tagger/note_parser.py: Parse .md notes, detect tag lines (config-driven)
- auto_tagger/classifier.py: Claude API batch classification (dynamic system prompt)
- auto_tagger/tag_inserter.py: Idempotent tag insertion with atomic writes
- auto_tagger/progress.py: JSON-based progress tracking with resume

## Key invariants
- Tag insertion is idempotent (running twice produces same result)
- Atomic writes (tempfile + rename) prevent partial file corruption
- Line count must be preserved after tag insertion
- PascalCase normalization for all tags
- All vault-specific knowledge lives in config.json (no hardcoded paths)
