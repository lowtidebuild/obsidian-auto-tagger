"""CLI interface for Obsidian Auto Tagger."""

import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

import click

from auto_tagger.config import (
    load_config,
    save_config,
    validate_config,
    ConfigError,
)
from auto_tagger.scanner import scan_vault
from auto_tagger.taxonomy import (
    extract_taxonomy_from_dir,
    save_taxonomy,
    load_taxonomy,
    add_new_tags_dynamic,
)
from auto_tagger.note_parser import (
    collect_notes_with_config,
    is_embed_only,
)
from auto_tagger.classifier import (
    classify_with_retry_dynamic,
    DynamicClassificationResult,
)
from auto_tagger.tag_inserter import insert_tags_dynamic
from auto_tagger.progress import (
    init_progress,
    save_progress,
    load_progress,
    mark_batch_completed,
    mark_files_retry,
    get_pending_files,
    get_stats,
)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BATCH_DELAY_SECONDS = 0.5


def _config_path():
    return os.path.join(PROJECT_DIR, "config.json")


def _taxonomy_path():
    return os.path.join(PROJECT_DIR, "taxonomy.json")


def _progress_path():
    return os.path.join(PROJECT_DIR, "progress.json")


def _load_config_or_exit() -> dict:
    """Load config.json or exit with helpful error."""
    try:
        config = load_config(_config_path())
        validate_config(config)
        return config
    except FileNotFoundError:
        click.echo("Error: config.json not found. Run 'init' command first.", err=True)
        click.echo("  python -m auto_tagger init /path/to/vault", err=True)
        sys.exit(1)
    except ConfigError as e:
        click.echo(f"Error in config.json: {e}", err=True)
        sys.exit(1)


@click.group()
def cli():
    """Obsidian Auto Tagger: Config-driven tagging for any Obsidian vault."""
    pass


@cli.command()
@click.argument("vault_path", type=click.Path(exists=True))
@click.option("--output", default=None, help="Output path for config.json")
def init(vault_path, output):
    """Scan a vault and generate config.json.

    VAULT_PATH is the root directory of your Obsidian vault.
    """
    output = output or _config_path()
    vault_path = os.path.abspath(vault_path)

    click.echo(f"Scanning vault: {vault_path}")
    click.echo("Detecting structure...")

    config = scan_vault(vault_path)

    click.echo(f"\nDetected {len(config['tag_prefixes'])} tag prefixes: {config['tag_prefixes']}")
    click.echo(f"Detected {len(config['note_directories'])} note directories:")
    for nd in config["note_directories"]:
        click.echo(f"  {nd['path']} (label: {nd['label']})")

    if config["taxonomy_source"]:
        click.echo(f"Taxonomy source: {config['taxonomy_source']}")
    else:
        click.echo("WARNING: No taxonomy source detected (cold start).")
        click.echo("  You can manually set taxonomy_source in config.json")

    if not config["tag_prefixes"]:
        click.echo("\nWARNING: No tag prefixes found in vault.")
        click.echo("  You may need to manually add tag_prefixes to config.json")
        click.echo('  Example: "tag_prefixes": ["topic", "theme"]')

    save_config(config, output)
    click.echo(f"\nSaved config to: {output}")
    click.echo("Review and edit config.json, then run 'taxonomy' and 'tag' commands.")


@cli.command()
@click.option("--output", default=None, help="Output path for taxonomy.json")
def taxonomy(output):
    """Extract tag taxonomy from configured taxonomy source."""
    config = _load_config_or_exit()
    output = output or _taxonomy_path()

    taxonomy_source = config["taxonomy_source"]
    if not taxonomy_source:
        click.echo("Error: No taxonomy_source configured. Edit config.json.", err=True)
        sys.exit(1)

    source_dir = os.path.join(config["vault_path"], taxonomy_source)
    prefixes = config["tag_prefixes"]

    click.echo(f"Scanning taxonomy source: {source_dir}")
    click.echo(f"Tag prefixes: {prefixes}")

    try:
        tax = extract_taxonomy_from_dir(source_dir, prefixes)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    save_taxonomy(tax, output)

    for prefix in prefixes:
        click.echo(f"Found {len(tax.get(prefix, []))} {prefix} tags")
    click.echo(f"Saved to {output}")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Preview without modifying files")
@click.option("--resume", is_flag=True, help="Resume from last progress")
@click.option("--batch-size", default=None, type=int, help="Notes per API batch (overrides config)")
@click.option("--model", default=None, type=click.Choice(["haiku", "sonnet"]), help="Model (overrides config)")
@click.option("--path", "sub_path", default=None, help="Subfolder to process (relative to vault)")
def tag(dry_run, resume, batch_size, model, sub_path):
    """Classify and tag notes using AI."""
    config = _load_config_or_exit()
    taxonomy_path = _taxonomy_path()
    progress_path = _progress_path()
    prefixes = config["tag_prefixes"]

    batch_size = batch_size or config.get("batch_size", 10)
    model = model or config.get("model", "haiku")

    # Load taxonomy
    try:
        tax = load_taxonomy(taxonomy_path)
    except FileNotFoundError:
        click.echo("Error: taxonomy.json not found. Run 'taxonomy' command first.", err=True)
        sys.exit(1)

    for prefix in prefixes:
        click.echo(f"Loaded {len(tax.get(prefix, []))} {prefix} tags")

    # Collect notes
    all_notes = collect_notes_with_config(config, sub_path=sub_path)
    click.echo(f"Found {len(all_notes)} notes total")

    # Filter already tagged
    untagged = [n for n in all_notes if not n.has_topic_theme]
    skipped_count = len(all_notes) - len(untagged)
    click.echo(f"Skipping {skipped_count} already tagged, {len(untagged)} to process")

    if not untagged:
        click.echo("Nothing to process.")
        return

    # Handle resume
    if resume:
        progress = load_progress(progress_path)
        if progress is None:
            click.echo("Error: No previous progress found.", err=True)
            sys.exit(1)
        pending_paths = set(get_pending_files(progress))
        untagged = [n for n in untagged if n.file_path in pending_paths]
        click.echo(f"Resuming: {len(untagged)} files remaining")
    else:
        progress = init_progress(
            total_files=len(untagged),
            file_paths=[n.file_path for n in untagged],
        )
        progress["skipped"] = skipped_count

    # Embed-only handling
    sibling_map = _build_sibling_map(untagged)
    classifiable = [n for n in untagged if not _is_embed_only_safe(n)]
    embed_only = [n for n in untagged if _is_embed_only_safe(n)]

    click.echo(f"Classifiable: {len(classifiable)}, Embed-only (inherit): {len(embed_only)}")

    # Process in batches
    batch_id = max((b["id"] for b in progress["batches"]), default=0)
    results_by_path: dict[str, DynamicClassificationResult] = {}

    for i in range(0, len(classifiable), batch_size):
        batch = classifiable[i:i + batch_size]
        batch_id += 1

        progress["batches"].append({
            "id": batch_id,
            "files": [n.file_path for n in batch],
            "status": "processing",
        })

        click.echo(f"\nBatch {batch_id}: {len(batch)} notes (model={model})")

        if dry_run:
            successes, failures = classify_with_retry_dynamic(batch, tax, prefixes, model)
            for result in successes:
                tl = _get_tag_line_from_list(result.file_path, batch)
                dry_result = insert_tags_dynamic(
                    result.file_path, tl, result.tags, dry_run=True
                )
                click.echo(f"  {os.path.basename(result.file_path)}")
                click.echo(f"    Before: {dry_result['before']}")
                click.echo(f"    After:  {dry_result['after']}")
            if failures:
                click.echo(f"  Failed: {len(failures)} notes")
            if i + batch_size < len(classifiable):
                time.sleep(BATCH_DELAY_SECONDS)
            continue

        # Real execution
        successes, failures = classify_with_retry_dynamic(batch, tax, prefixes, model)

        for result in successes:
            results_by_path[result.file_path] = result
            tl = _get_tag_line_from_list(result.file_path, batch)
            insert_tags_dynamic(result.file_path, tl, result.tags)
            click.echo(f"  Tagged: {os.path.basename(result.file_path)} {result.tags}")

            if result.has_new_tags:
                new_tags = {}
                for prefix in prefixes:
                    new_for_prefix = [
                        t for t in result.tags.get(prefix, [])
                        if t not in tax.get(prefix, [])
                    ]
                    if new_for_prefix:
                        new_tags[prefix] = new_for_prefix
                if new_tags:
                    add_new_tags_dynamic(taxonomy_path, new_tags)
                    tax = load_taxonomy(taxonomy_path)
                    for prefix, tags in new_tags.items():
                        for t in tags:
                            if t not in progress["new_tags_proposed"]:
                                progress["new_tags_proposed"].append(t)
                    click.echo(f"  [NEW] tags added: {new_tags}")

        progress = mark_batch_completed(progress, batch_id)

        if failures:
            progress = mark_files_retry(progress, failures)
            click.echo(f"  Retry queued: {len(failures)} notes")

        save_progress(progress, progress_path)

        if i + batch_size < len(classifiable):
            time.sleep(BATCH_DELAY_SECONDS)

    # Process embed-only notes
    if not dry_run and embed_only:
        click.echo(f"\nInheriting tags for {len(embed_only)} embed-only notes...")
        for note in embed_only:
            sibling_result = _find_sibling_result_dynamic(note, sibling_map, results_by_path)
            if sibling_result:
                insert_tags_dynamic(note.file_path, note.tag_line_num, sibling_result.tags)
                progress["processed"] += 1
                click.echo(f"  Inherited: {os.path.basename(note.file_path)}")
            else:
                progress["skipped"] += 1
                click.echo(f"  Skipped (no sibling): {os.path.basename(note.file_path)}")
        save_progress(progress, progress_path)

    if not dry_run:
        stats = get_stats(progress)
        click.echo(f"\nDone! Processed: {stats['processed']}, "
                   f"Skipped: {stats['skipped']}, Failed: {stats['failed']}")
        if stats["new_tags"]:
            click.echo(f"New tags added: {stats['new_tags']}")


@cli.command()
def stats():
    """Show tagging statistics for the configured vault."""
    config = _load_config_or_exit()
    prefixes = config["tag_prefixes"]

    all_notes = collect_notes_with_config(config)
    tagged = [n for n in all_notes if n.has_topic_theme]
    untagged = [n for n in all_notes if not n.has_topic_theme]

    click.echo(f"Total notes: {len(all_notes)}")
    click.echo(f"Tagged: {len(tagged)}")
    click.echo(f"Untagged: {len(untagged)}")

    if tagged:
        for prefix in prefixes:
            counts: dict[str, int] = {}
            for note in tagged:
                for tag_str in note.existing_tags:
                    if tag_str.startswith(f"#{prefix}/"):
                        name = tag_str.replace(f"#{prefix}/", "")
                        counts[name] = counts.get(name, 0) + 1
            click.echo(f"\nTop 10 {prefix.capitalize()}s:")
            for name, count in sorted(counts.items(), key=lambda x: -x[1])[:10]:
                click.echo(f"  {name}: {count}")

    progress = load_progress(_progress_path())
    if progress:
        pstats = get_stats(progress)
        click.echo(f"\nLast run: processed={pstats['processed']}, "
                   f"skipped={pstats['skipped']}, failed={pstats['failed']}")


# --- Helper functions ---

def _get_tag_line_from_list(file_path: str, notes: list) -> int:
    for n in notes:
        if n.file_path == file_path:
            return n.tag_line_num
    return 0


def _build_sibling_map(notes: list) -> dict[str, list]:
    sibling_map: dict[str, list] = {}
    for note in notes:
        dir_path = os.path.dirname(note.file_path)
        sibling_map.setdefault(dir_path, []).append(note)
    return sibling_map


def _is_embed_only_safe(note) -> bool:
    """Check if a note is embed-only, safely handling errors."""
    try:
        return is_embed_only(note.file_path)
    except Exception:
        return False


def _find_sibling_result_dynamic(
    embed_note,
    sibling_map: dict,
    results_by_path: dict[str, DynamicClassificationResult],
) -> DynamicClassificationResult | None:
    dir_path = os.path.dirname(embed_note.file_path)
    siblings = sibling_map.get(dir_path, [])
    for sibling in siblings:
        if sibling.file_path == embed_note.file_path:
            continue
        if sibling.file_path in results_by_path:
            return results_by_path[sibling.file_path]
    return None


if __name__ == "__main__":
    cli()
