"""CLI interface for Obsidian Auto-Tagger."""

import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

import click

from auto_tagger.taxonomy import extract_taxonomy, save_taxonomy, load_taxonomy, add_new_tags
from auto_tagger.note_parser import collect_notes, is_embed_only, parse_note
from auto_tagger.classifier import classify_with_retry, ClassificationResult
from auto_tagger.tag_inserter import insert_tags
from auto_tagger.progress import (
    init_progress,
    save_progress,
    load_progress,
    mark_batch_completed,
    mark_files_retry,
    get_pending_files,
    get_stats,
)

VAULT_ROOT_DEFAULT = "/Users/lowtidebuild/Obsidian/5. Zettelkasten"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Delay between API batches to avoid rate limiting
BATCH_DELAY_SECONDS = 0.5


def _taxonomy_path():
    return os.path.join(PROJECT_DIR, "taxonomy.json")


def _progress_path():
    return os.path.join(PROJECT_DIR, "progress.json")


@click.group()
def cli():
    """Obsidian Auto-Tagger: Apply topic/theme tags to NotebookLM notes."""
    pass


@cli.command()
@click.option("--vault", default=VAULT_ROOT_DEFAULT, help="Obsidian vault root path")
@click.option("--output", default=None, help="Output path for taxonomy.json")
def taxonomy(vault, output):
    """Extract tag taxonomy from reading notes."""
    output = output or _taxonomy_path()
    click.echo(f"Scanning reading notes in {vault}...")

    try:
        tax = extract_taxonomy(vault)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    save_taxonomy(tax, output)
    click.echo(f"Found {len(tax['topics'])} topics, {len(tax['themes'])} themes")
    click.echo(f"Saved to {output}")


@cli.command()
@click.option("--vault", default=VAULT_ROOT_DEFAULT, help="Obsidian vault root path")
@click.option("--dry-run", is_flag=True, help="Preview without modifying files")
@click.option("--resume", is_flag=True, help="Resume from last progress")
@click.option("--batch-size", default=10, help="Notes per API batch")
@click.option("--model", default="haiku", type=click.Choice(["haiku", "sonnet"]))
@click.option("--path", "sub_path", default=None, help="Subfolder to process (relative to vault)")
def tag(vault, dry_run, resume, batch_size, model, sub_path):
    """Classify and tag NotebookLM notes."""
    taxonomy_path = _taxonomy_path()
    progress_path = _progress_path()

    # Load taxonomy
    try:
        tax = load_taxonomy(taxonomy_path)
    except FileNotFoundError:
        click.echo("Error: taxonomy.json not found. Run 'taxonomy' command first.", err=True)
        sys.exit(1)

    click.echo(f"Loaded taxonomy: {len(tax['topics'])} topics, {len(tax['themes'])} themes")

    # Collect notes
    all_notes = collect_notes(vault, sub_path=sub_path)
    click.echo(f"Found {len(all_notes)} notes total")

    # Filter out already tagged
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

    # Handle Resources embed-only: collect sibling mapping
    sibling_map = _build_sibling_map(untagged)

    # Process in batches
    batch_id = max((b["id"] for b in progress["batches"]), default=0)

    # Separate classifiable notes from embed-only notes
    classifiable = [n for n in untagged if not (n.source_folder == "resources" and is_embed_only(n.file_path))]
    embed_only = [n for n in untagged if n.source_folder == "resources" and is_embed_only(n.file_path)]

    click.echo(f"Classifiable: {len(classifiable)}, Embed-only (inherit): {len(embed_only)}")

    # Process classifiable notes in batches
    results_by_path: dict[str, ClassificationResult] = {}

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
            # Still call API for dry-run preview
            successes, failures = classify_with_retry(batch, tax, model)
            for result in successes:
                dry_result = insert_tags(
                    result.file_path,
                    tag_line_num=_get_tag_line(result.file_path, batch),
                    topics=result.topics,
                    themes=result.themes,
                    dry_run=True,
                )
                click.echo(f"  {os.path.basename(result.file_path)}")
                click.echo(f"    Before: {dry_result['before']}")
                click.echo(f"    After:  {dry_result['after']}")
            if failures:
                click.echo(f"  Failed: {len(failures)} notes")
            # Don't update progress in dry-run
            if i + batch_size < len(classifiable):
                time.sleep(BATCH_DELAY_SECONDS)
            continue

        # Real execution
        successes, failures = classify_with_retry(batch, tax, model)

        for result in successes:
            results_by_path[result.file_path] = result

            # Insert tags
            tl = _get_tag_line(result.file_path, batch)
            insert_tags(result.file_path, tl, result.topics, result.themes)
            click.echo(f"  Tagged: {os.path.basename(result.file_path)} "
                       f"topics={result.topics} themes={result.themes}")

            # Handle [NEW] tags
            if result.has_new_tags:
                new_topics = [t for t in result.topics if t not in tax["topics"]]
                new_themes = [t for t in result.themes if t not in tax["themes"]]
                if new_topics or new_themes:
                    add_new_tags(taxonomy_path, new_topics, new_themes)
                    tax = load_taxonomy(taxonomy_path)
                    for t in new_topics + new_themes:
                        if t not in progress["new_tags_proposed"]:
                            progress["new_tags_proposed"].append(t)
                    click.echo(f"  [NEW] tags added: {new_topics + new_themes}")

        # Mark batch
        progress = mark_batch_completed(progress, batch_id)

        # Handle failures
        if failures:
            progress = mark_files_retry(progress, failures)
            click.echo(f"  Retry queued: {len(failures)} notes")

        save_progress(progress, progress_path)

        # Delay between batches to avoid rate limiting
        if i + batch_size < len(classifiable):
            time.sleep(BATCH_DELAY_SECONDS)

    # Process embed-only notes: inherit from sibling
    if not dry_run and embed_only:
        click.echo(f"\nInheriting tags for {len(embed_only)} embed-only notes...")
        for note in embed_only:
            sibling_result = _find_sibling_result(note, sibling_map, results_by_path)
            if sibling_result:
                insert_tags(
                    note.file_path,
                    note.tag_line_num,
                    sibling_result.topics,
                    sibling_result.themes,
                )
                progress["processed"] += 1
                click.echo(f"  Inherited: {os.path.basename(note.file_path)} "
                           f"<- {os.path.basename(sibling_result.file_path)}")
            else:
                progress["skipped"] += 1
                click.echo(f"  Skipped (no sibling): {os.path.basename(note.file_path)}")
        save_progress(progress, progress_path)

    # Final stats
    if not dry_run:
        stats = get_stats(progress)
        click.echo(f"\nDone! Processed: {stats['processed']}, "
                   f"Skipped: {stats['skipped']}, Failed: {stats['failed']}")
        if stats["new_tags"]:
            click.echo(f"New tags added: {stats['new_tags']}")


@cli.command()
@click.option("--vault", default=VAULT_ROOT_DEFAULT, help="Obsidian vault root path")
def stats(vault):
    """Show tagging statistics for the vault."""
    all_notes = collect_notes(vault)
    tagged = [n for n in all_notes if n.has_topic_theme]
    untagged = [n for n in all_notes if not n.has_topic_theme]

    click.echo(f"Total NotebookLM notes: {len(all_notes)}")
    click.echo(f"Tagged (has topic/theme): {len(tagged)}")
    click.echo(f"Untagged: {len(untagged)}")

    if tagged:
        # Count tag frequency
        topic_counts: dict[str, int] = {}
        theme_counts: dict[str, int] = {}
        for note in tagged:
            for tag_str in note.existing_tags:
                if tag_str.startswith("#topic/"):
                    name = tag_str.replace("#topic/", "")
                    topic_counts[name] = topic_counts.get(name, 0) + 1
                elif tag_str.startswith("#theme/"):
                    name = tag_str.replace("#theme/", "")
                    theme_counts[name] = theme_counts.get(name, 0) + 1

        click.echo("\nTop 10 Topics:")
        for name, count in sorted(topic_counts.items(), key=lambda x: -x[1])[:10]:
            click.echo(f"  {name}: {count}")

        click.echo("\nTop 10 Themes:")
        for name, count in sorted(theme_counts.items(), key=lambda x: -x[1])[:10]:
            click.echo(f"  {name}: {count}")

    # Show progress if available
    progress = load_progress(_progress_path())
    if progress:
        pstats = get_stats(progress)
        click.echo(f"\nLast run: processed={pstats['processed']}, "
                   f"skipped={pstats['skipped']}, failed={pstats['failed']}")
        if pstats["new_tags"]:
            click.echo(f"New tags proposed: {pstats['new_tags']}")


def _get_tag_line(file_path: str, notes: list) -> int:
    """Get tag_line_num for a file from the notes list."""
    for n in notes:
        if n.file_path == file_path:
            return n.tag_line_num
    # Fallback: re-parse
    from auto_tagger.note_parser import _detect_source_folder
    note = parse_note(file_path, _detect_source_folder(file_path))
    return note.tag_line_num


def _build_sibling_map(notes: list) -> dict[str, list]:
    """
    Build a mapping from directory path to list of notes in that directory.
    Used for Resources embed-only sibling inheritance.
    """
    sibling_map: dict[str, list] = {}
    for note in notes:
        dir_path = os.path.dirname(note.file_path)
        sibling_map.setdefault(dir_path, []).append(note)
    return sibling_map


def _find_sibling_result(
    embed_note,
    sibling_map: dict,
    results_by_path: dict[str, ClassificationResult],
) -> ClassificationResult | None:
    """
    Find a classified sibling in the same directory to inherit tags from.
    """
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
