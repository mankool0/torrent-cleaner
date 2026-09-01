"""Main entry point for torrent cleaner."""

import sys
import os
import fcntl
from pathlib import Path
import logging
from datetime import datetime
from collections import defaultdict

from src.config import Config
from src.utils.logger import setup_logger
from src.qbittorrent_client import QBittorrentClient
from src.file_analyzer import FileAnalyzer
from src.hardlink_fixer import HardlinkFixer
from src.torrent_cleaner import TorrentCleaner
from src.discord_notifier import DiscordNotifier
from src.models import HardlinkFailure, SizeIndex, WorkflowStats
from typing import Dict, List
import qbittorrentapi


class SpaceAccountant:
    """Track pending unlinks per inode to accurately estimate freed disk space.

    When files are hardlinked, deleting one link doesn't free space — only
    removing the last link does. This class tracks how many links we plan to
    remove per inode and only counts the file size when all links are gone.
    """

    def __init__(self):
        self._pending_unlinks: Dict[int, int] = defaultdict(int)
        self._nlinks: Dict[int, int] = {}
        self._sizes: Dict[int, int] = {}

    def estimate_freed(self, file_paths: List[str]) -> int:
        """Estimate bytes freed by deleting the given file paths.

        Tracks inodes across calls so that hardlinked files shared between
        multiple torrents are only counted once (when the last link is removed).
        Missing files are silently skipped.
        """
        freed = 0
        for path in file_paths:
            try:
                stat = os.stat(path)
            except OSError:
                continue
            inode = stat.st_ino
            if inode not in self._nlinks:
                self._nlinks[inode] = stat.st_nlink
                self._sizes[inode] = stat.st_size
            self._pending_unlinks[inode] += 1
            if self._nlinks[inode] == self._pending_unlinks[inode]:
                freed += self._sizes[inode]
        return freed


def is_dead_tracker_torrent(qbt_client: QBittorrentClient, torrent: qbittorrentapi.TorrentDictionary, dead_messages: List[str]) -> bool:
    """
    Check if all real trackers for a torrent report known-dead messages.

    Args:
        qbt_client: QBittorrentClient instance
        torrent: Torrent dictionary from qBittorrent API
        dead_messages: Messages compared for exact (case-insensitive) equality
                       against tracker error messages

    Returns:
        True if all real trackers are dead
    """
    logger = logging.getLogger(__name__)
    try:
        trackers = qbt_client.torrents_trackers(torrent.hash)
    except Exception as e:
        logger.warning(f"Could not get trackers for {torrent.name}: {e}")
        return False

    # Filter out DHT/PeX/LSD pseudo-trackers (url starts with **)
    real_trackers = [t for t in trackers if not t.url.startswith('**')]

    if not real_trackers:
        return False

    dead_msgs = {dead_msg.lower() for dead_msg in dead_messages}
    for tracker in real_trackers:
        # status 4 = contacted but not working; qBittorrent 5.1 split off
        # status 5 = tracker responded but rejected the announce (the message
        # states why, e.g. "unregistered torrent")
        if tracker.status not in (4, 5):
            return False
        msg = (tracker.msg or '').lower()
        if msg not in dead_msgs:
            return False

    return True


def _remove_unshared_files(paths: List[str], save_path: Path, dry_run: bool) -> None:
    """Unlink a deleted dead torrent's files that no surviving torrent references.

    Used when shared files forced an entry-only deletion: qBittorrent's delete
    is all-or-nothing, so the unshared leftovers (e.g. a sample file) are
    removed here instead. Directories emptied by this are pruned, but never
    the save path itself (other torrents live there).
    """
    logger = logging.getLogger(__name__)
    save_path_resolved = Path(os.path.realpath(save_path))
    for path in paths:
        if dry_run:
            logger.info(f"  [DRY RUN] Would remove unshared file: {path}")
            continue
        try:
            os.unlink(path)
            logger.info(f"  Removed unshared file: {path}")
        except OSError as e:
            logger.error(f"  Failed to remove unshared file {path}: {e}")
            continue
        parent = Path(path).parent
        try:
            while True:
                parent_resolved = Path(os.path.realpath(parent))
                if parent_resolved == save_path_resolved or save_path_resolved not in parent_resolved.parents:
                    break
                os.rmdir(parent)  # only removes empty directories
                parent = parent.parent
        except OSError:
            pass  # directory not empty - stop pruning


def _deletion_cap_reached(config: Config, stats: WorkflowStats) -> bool:
    """Check whether this run's deletion cap (MAX_DELETIONS_PER_RUN) has been reached."""
    return config.max_deletions_per_run > 0 and stats.torrents_deleted >= config.max_deletions_per_run


def run_workflow(config: Config, qbt_client: QBittorrentClient, file_analyzer: FileAnalyzer, hardlink_fixer: HardlinkFixer, torrent_cleaner: TorrentCleaner, size_index: SizeIndex) -> WorkflowStats:
    """
    Run the torrent cleaning workflow.

    Args:
        config: Config object
        qbt_client: QBittorrentClient instance
        file_analyzer: FileAnalyzer instance
        hardlink_fixer: HardlinkFixer instance
        torrent_cleaner: TorrentCleaner instance
        size_index: SizeIndex mapping file sizes to lists of file paths

    Returns:
        WorkflowStats with workflow statistics
    """
    logger = logging.getLogger(__name__)
    stats = WorkflowStats()
    space_accountant = SpaceAccountant()

    logger.info("Retrieving torrents from qBittorrent...")
    torrents = qbt_client.torrents_info()

    # --- Preflight: verify torrent paths are visible from this container ---
    # If none of qBittorrent's save paths exist here, the volume mounts or path
    # mapping are misconfigured and every torrent would look unlinked. Deleting
    # on that signal destroys data, so refuse to continue.
    save_paths = {str(t.save_path) for t in torrents}
    missing_paths = {p for p in save_paths if not Path(p).exists()}
    for p in sorted(missing_paths)[:5]:
        logger.warning(f"Torrent save path not visible from this container: {p}")
    if save_paths and missing_paths == save_paths:
        message = (
            "None of the torrent save paths reported by qBittorrent exist in this "
            "container - the volume mounts or path mapping are misconfigured. "
            f"Examples: {', '.join(sorted(missing_paths)[:3])}"
        )
        if config.dry_run:
            logger.warning(f"[DRY RUN] {message}")
        else:
            raise RuntimeError(message)

    # --- Dead tracker pass ---
    deleted_hashes = set()
    if config.delete_dead_trackers:
        if not config.dead_tracker_messages:
            logger.warning("DELETE_DEAD_TRACKERS is enabled but DEAD_TRACKER_MESSAGES is empty - no torrents will match")
        logger.info("Checking for dead tracker torrents...")
        dead_torrents = [
            t for t in torrents
            if is_dead_tracker_torrent(qbt_client, t, config.dead_tracker_messages)
        ]

        # Cross-seeds can share a dead torrent's files: another torrent added at
        # the same path, or a link that resolves there. Deleting the files would
        # break those survivors, so collect every path the kept torrents resolve
        # to and never delete a file that is still referenced.
        surviving_paths = set()
        survivors_unlisted = 0
        if dead_torrents:
            dead_hash_set = {t.hash for t in dead_torrents}
            for torrent in torrents:
                if torrent.hash in dead_hash_set:
                    continue
                try:
                    for tf in qbt_client.torrents_files(torrent.hash):
                        surviving_paths.add(os.path.realpath(str(Path(torrent.save_path) / tf.name)))
                except Exception as e:
                    survivors_unlisted += 1
                    logger.warning(f"  Could not list files for surviving torrent {torrent.name}: {e}")

        if survivors_unlisted:
            # Without the full survivor file list no file deletion can be
            # proven safe - keep everything and let the next run retry
            logger.warning(
                f"Skipping dead tracker deletions: file lists unavailable for {survivors_unlisted} "
                f"surviving torrent(s), so shared files cannot be ruled out"
            )
            dead_torrents = []

        for torrent in dead_torrents:
            logger.info(f"  Dead tracker detected: {torrent.name}")

            if _deletion_cap_reached(config, stats):
                logger.warning(
                    f"  Skipping deletion (MAX_DELETIONS_PER_RUN={config.max_deletions_per_run} reached): {torrent.name}"
                )
                stats.deletions_skipped_cap += 1
                continue

            try:
                torrent_files = qbt_client.torrents_files(torrent.hash)
                dead_file_paths = [str(Path(torrent.save_path) / tf.name) for tf in torrent_files]
            except Exception as e:
                logger.warning(f"  Keeping dead tracker torrent (could not list files): {torrent.name}: {e}")
                continue

            # Removing the torrent ENTRY is always data-safe; removing its
            # FILES is not. Keep every file when they are invisible from here
            # (usually a path/mount misconfiguration). When only some files
            # are shared with surviving torrents (cross-seed at the same path),
            # qBt's all-or-nothing delete can't split them: remove the entry
            # without files, then unlink the unshared leftovers directly.
            missing = [p for p in dead_file_paths if not os.path.exists(p)]
            shared = [p for p in dead_file_paths if os.path.realpath(p) in surviving_paths]
            delete_files = not missing and not shared
            unshared = []
            if missing:
                logger.warning(
                    f"  {len(missing)} file(s) not visible from this container - "
                    f"deleting torrent but keeping files: {torrent.name}"
                )
            elif shared:
                unshared = [p for p in dead_file_paths if os.path.realpath(p) not in surviving_paths]
                logger.info(
                    f"  {len(shared)} file(s) shared with surviving torrents (cross-seed) - "
                    f"deleting torrent, keeping shared files"
                    + (f", removing {len(unshared)} unshared file(s)" if unshared else "")
                    + f": {torrent.name}"
                )

            if delete_files:
                size = space_accountant.estimate_freed(dead_file_paths)
            elif unshared:
                size = space_accountant.estimate_freed(unshared)
            else:
                size = 0
            success = torrent_cleaner.delete_torrent(
                torrent.hash,
                torrent.name,
                delete_files=delete_files
            )
            if success:
                if unshared:
                    _remove_unshared_files(unshared, Path(torrent.save_path), config.dry_run)
                deleted_hashes.add(torrent.hash)
                stats.torrents_deleted_dead_tracker += 1
                stats.space_freed_dead_tracker_bytes += size
                if delete_files:
                    label = "[dead tracker]"
                elif missing:
                    label = "[dead tracker, files kept]"
                else:
                    label = "[dead tracker, shared files kept]"
                stats.deleted_torrents.append(f"{label} {torrent.name}")
                stats.torrents_deleted += 1
                stats.torrents_processed += 1

        if deleted_hashes:
            logger.info(f"Dead tracker pass: deleted {len(deleted_hashes)} torrent(s)")
            # Re-fetch torrents to get fresh state after deletions
            torrents = qbt_client.torrents_info()
            # Filter out dry-run "deleted" torrents that still exist in qBittorrent
            torrents = [t for t in torrents if t.hash not in deleted_hashes]
        else:
            logger.info("Dead tracker pass: no dead tracker torrents found")

    # Build torrent groups for aggregation
    # When multiple torrents share files (hardlinked), aggregate their stats
    logger.info("Building torrent groups for stat aggregation...")
    inode_to_torrents = defaultdict(set)
    torrent_hash_to_torrent = {t.hash: t for t in torrents}

    for torrent in torrents:
        try:
            save_path = Path(torrent.save_path)
            torrent_files = qbt_client.torrents_files(torrent.hash)

            for tf in torrent_files:
                file_path = save_path / tf.name
                if file_path.exists():
                    inode = os.stat(file_path).st_ino
                    inode_to_torrents[inode].add(torrent.hash)
        except Exception as e:
            logger.warning(f"Could not get file info for torrent {torrent.name}: {e}")

    # Build torrent groups (torrents sharing at least one file)
    torrent_to_group = {}
    for inode, torrent_hashes in inode_to_torrents.items():
        if len(torrent_hashes) > 1:
            # Multiple torrents share this file - they're in a group
            group = set(torrent_hashes)
            # Merge with existing groups
            for th in list(torrent_hashes):
                if th in torrent_to_group:
                    group.update(torrent_to_group[th])
            # Update all torrents in the merged group
            for th in group:
                torrent_to_group[th] = group

    # Calculate aggregate stats for each group
    group_stats = {}
    for torrent_hash, group in torrent_to_group.items():
        group_key = frozenset(group)
        if group_key not in group_stats:
            max_seeding_time = max(torrent_hash_to_torrent[th].seeding_time for th in group)
            sum_ratio = sum(torrent_hash_to_torrent[th].ratio for th in group)
            group_stats[group_key] = {
                'seeding_time': max_seeding_time,
                'ratio': sum_ratio
            }
            logger.info(f"  Group of {len(group)} torrents: max_seeding_time={max_seeding_time}s, sum_ratio={sum_ratio:.2f}")

    logger.info(f"Processing {len(torrents)} torrents...")
    processed_count = 0
    for torrent in torrents:
        stats.torrents_processed += 1
        processed_count += 1

        torrent_name = torrent.name
        torrent_hash = torrent.hash
        save_path = Path(torrent.save_path)

        logger.info(f"\nProcessing torrent [{processed_count}/{len(torrents)}]: {torrent_name}")

        # Check if torrent is part of a group
        if torrent_hash in torrent_to_group:
            group_key = frozenset(torrent_to_group[torrent_hash])
            aggregate = group_stats[group_key]
            logger.info(f"  Part of group with {len(torrent_to_group[torrent_hash])} torrents: "
                       f"aggregate seeding_time={aggregate['seeding_time']}s, ratio={aggregate['ratio']:.2f}")
            deletion_check = torrent_cleaner.should_delete_torrent(
                torrent,
                override_seeding_time=aggregate['seeding_time'],
                override_ratio=aggregate['ratio']
            )
        else:
            deletion_check = torrent_cleaner.should_delete_torrent(torrent)

        logger.info(f"  Deletion check: {', '.join(deletion_check.reasons)}")

        # Skip incomplete torrents (no files to process)
        if deletion_check.stats.seeding_time_seconds is None:
            stats.torrents_kept += 1
            stats.torrents_kept_criteria_not_met += 1
            continue

        # --- Hardlink analysis and fixing (all completed torrents) ---
        try:
            torrent_files = qbt_client.torrents_files(torrent_hash)
            file_paths = [str(save_path / tf.name) for tf in torrent_files]

            logger.info(f"  Found {len(file_paths)} files in torrent")

            analysis = file_analyzer.detect_orphaned_files(file_paths)
            orphaned_files = analysis.orphaned
            stats.orphaned_files_found += len(orphaned_files)

            logger.info(
                f"  Hardlink analysis: {len(orphaned_files)} orphaned, "
                f"{len(analysis.linked)} linked"
            )

            # Never act on a torrent whose files we couldn't inspect — a wrong
            # mount/path config makes every file look missing, and deleting on
            # that signal destroys data
            if analysis.stats.errors > 0:
                logger.warning(
                    f"  Keeping torrent ({analysis.stats.errors} file(s) could not be checked - "
                    f"possible path/mount misconfiguration)"
                )
                stats.torrents_kept += 1
                stats.torrents_kept_file_errors += 1
                continue

            has_actionable_failures = False
            media_files_fixed = 0
            if config.fix_hardlinks and orphaned_files:
                # Pause torrent to prevent redownload during hardlink fix
                paused = False
                if not config.dry_run:
                    logger.info(f"  Pausing torrent '{torrent_name}' during hardlink fix")
                    qbt_client.pause_torrent(torrent_hash)
                    paused = True

                try:
                    fix_results = hardlink_fixer.fix_orphaned_files(
                        orphaned_files,
                        size_index,
                        file_analyzer,
                        dry_run=config.dry_run,
                        byte_verify=config.hardlink_byte_verify
                    )
                finally:
                    # Resume even if fixing raised — a torrent left paused
                    # forever is worse than a failed fix
                    if paused:
                        logger.info(f"  Resuming torrent '{torrent_name}' after hardlink fix")
                        try:
                            qbt_client.resume_torrent(torrent_hash)
                        except Exception as resume_error:
                            logger.error(f"  Failed to resume torrent '{torrent_name}': {resume_error}")

                stats.hardlinks_attempted += fix_results.attempted
                stats.hardlinks_fixed += fix_results.fixed
                stats.hardlinks_failed += fix_results.failed
                stats.space_saved_hardlinks_bytes += fix_results.bytes_saved
                media_files_fixed = fix_results.media_files_fixed

                # Track actionable hardlink failures
                for fix_result in fix_results.results:
                    if fix_result.result.action.is_actionable_failure:
                        has_actionable_failures = True
                        stats.hardlink_failures.append(HardlinkFailure(
                            torrent=torrent_name,
                            file=fix_result.file,
                            media_file=fix_result.media_file,
                            action=fix_result.result.action,
                            message=fix_result.result.message,
                        ))

            # --- Deletion decision ---
            if not deletion_check.should_delete:
                if media_files_fixed > 0:
                    logger.info(f"  Keeping torrent (criteria not met, fixed {media_files_fixed} media file(s))")
                    stats.torrents_kept_hardlinks_fixed += 1
                else:
                    logger.info(f"  Keeping torrent (criteria not met)")
                    stats.torrents_kept_criteria_not_met += 1
                stats.torrents_kept += 1
                continue

            # Block deletion if hardlink fixing had actionable failures
            if has_actionable_failures:
                logger.warning(
                    f"  Keeping torrent (hardlink fixing failed - requires manual intervention)"
                )
                stats.torrents_kept += 1
                stats.torrents_kept_hardlink_failures += 1
                continue

            # Check if files are already hardlinked to media library (only for deletion-eligible)
            media_files_already_linked = 0
            if analysis.linked:
                # Files are hardlinked - verify they're linked to media library
                for linked_file in analysis.linked:
                    if not file_analyzer.is_media_file(linked_file):
                        continue
                    # Check if this file exists in media library
                    if file_analyzer.find_identical_file(linked_file, size_index=size_index):
                        media_files_already_linked += 1

                if media_files_already_linked == 0:
                    logger.info(
                        f"  {len(analysis.linked)} linked file(s) match nothing in the media library "
                        f"(hardlinked elsewhere, e.g. a cross-seed)"
                    )

            if media_files_already_linked > 0 or media_files_fixed > 0:
                logger.info(
                    f"  Keeping torrent ({media_files_already_linked} media file(s) already hardlinked, "
                    f"{media_files_fixed} media file(s) fixed)"
                )
                stats.torrents_kept += 1
                stats.torrents_kept_hardlinks_fixed += 1
                continue

            if _deletion_cap_reached(config, stats):
                logger.warning(
                    f"  Skipping deletion (MAX_DELETIONS_PER_RUN={config.max_deletions_per_run} reached)"
                )
                stats.deletions_skipped_cap += 1
                stats.torrents_kept += 1
                continue

            logger.info(f"  Deleting torrent (meets criteria, no media files linked to media library)")

            freed = space_accountant.estimate_freed(file_paths)
            success = torrent_cleaner.delete_torrent(
                torrent_hash,
                torrent_name,
                delete_files=True
            )

            if success:
                stats.torrents_deleted += 1
                stats.space_freed_criteria_bytes += freed
                stats.deleted_torrents.append(torrent_name)

                reason_key = f"age={deletion_check.stats.age}, ratio={deletion_check.stats.ratio:.2f}"
                stats.deletion_reasons[reason_key] = stats.deletion_reasons.get(reason_key, 0) + 1

        except Exception as e:
            logger.error(f"  Error processing torrent files: {e}")
            continue

    return stats


def main() -> int:
    """Main workflow for torrent cleaning."""
    # Initialize a basic stderr logger before Config so startup errors are formatted
    logger = setup_logger('torrent-cleaner', 'INFO')

    try:
        config = Config()

        # Reconfigure logger with settings from config (log level + file)
        logger = setup_logger('torrent-cleaner', config.log_level, config.log_file, config.log_max_files)

        # Acquire exclusive lock to prevent concurrent runs
        lock_path = config.data_dir / '.cleaner.lock'
        lock_file = open(lock_path, 'w')
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("Another instance is already running — skipping this run")
            if config.discord_webhook_url:
                try:
                    DiscordNotifier(config.discord_webhook_url).send_error(
                        "Torrent Cleaner run skipped: another instance is already running"
                    )
                except Exception as e:
                    logger.error(f"Failed to send Discord skip notification: {e}")
            lock_file.close()
            return 0

        logger.info("=" * 80)
        logger.info("Torrent Cleaner Starting")
        logger.info("=" * 80)
        logger.info(f"\n{config}")

        if config.dry_run:
            logger.warning("Running in DRY RUN mode - no changes will be made")

        logger.info("Initializing components...")

        file_cache = None
        if config.enable_cache:
            from src.file_cache import FileCache
            try:
                file_cache = FileCache(db_path=config.cache_db_path)
                cache_stats = file_cache.get_stats()
                logger.info(f"File cache initialized ({cache_stats.total_entries} existing entries)")
            except Exception as e:
                logger.warning(f"Failed to initialize file cache: {e}")
                file_cache = None

        qbt_client = QBittorrentClient(
            config.qbt_host,
            config.qbt_port,
            config.qbt_username,
            config.qbt_password
        )
        file_analyzer = FileAnalyzer(cache=file_cache, media_extensions=config.media_extensions)
        hardlink_fixer = HardlinkFixer()
        torrent_cleaner = TorrentCleaner(config, qbt_client)
        discord_notifier = DiscordNotifier(config.discord_webhook_url)

        logger.info("Building media library size index...")
        size_index = file_analyzer.build_size_index(config.media_library_dir)

        # Safety: an empty index means every torrent looks unlinked and becomes
        # eligible for deletion — almost always a wrong/unmounted MEDIA_LIBRARY_DIR
        if size_index.file_count == 0 and not config.allow_empty_media_library:
            message = (
                f"Media library index is empty ({config.media_library_dir}) - every torrent "
                f"would look unlinked and become eligible for deletion. Check the volume mount "
                f"and MEDIA_LIBRARY_DIR, or set ALLOW_EMPTY_MEDIA_LIBRARY=true if this is intentional."
            )
            if config.dry_run:
                logger.warning(f"[DRY RUN] {message}")
            else:
                raise RuntimeError(message)

        stats = run_workflow(config, qbt_client, file_analyzer, hardlink_fixer, torrent_cleaner, size_index)

        qbt_client.close()

        logger.info("\n" + "=" * 80)
        logger.info("Torrent Cleaner Summary")
        logger.info("=" * 80)
        logger.info(f"Torrents processed: {stats.torrents_processed}")
        logger.info(f"Torrents deleted: {stats.torrents_deleted}")
        logger.info(f"Torrents kept: {stats.torrents_kept}")
        logger.info(f"  - Kept (criteria not met): {stats.torrents_kept_criteria_not_met}")
        logger.info(f"  - Kept (hardlinks fixed): {stats.torrents_kept_hardlinks_fixed}")
        logger.info(f"  - Kept (hardlink failures): {stats.torrents_kept_hardlink_failures}")
        logger.info(f"  - Kept (file errors): {stats.torrents_kept_file_errors}")
        if stats.deletions_skipped_cap:
            logger.warning(
                f"Deletions skipped (MAX_DELETIONS_PER_RUN={config.max_deletions_per_run} reached): "
                f"{stats.deletions_skipped_cap}"
            )
        logger.info(f"Hardlinks attempted: {stats.hardlinks_attempted}")
        logger.info(f"Hardlinks fixed: {stats.hardlinks_fixed}")
        logger.info(f"Hardlinks failed: {stats.hardlinks_failed}")
        logger.info(f"Orphaned files found: {stats.orphaned_files_found}")

        space_dead = stats.space_freed_dead_tracker_bytes / (1024**3)
        space_criteria = stats.space_freed_criteria_bytes / (1024**3)
        space_hardlinks = stats.space_saved_hardlinks_bytes / (1024**3)
        space_total = (stats.space_freed_dead_tracker_bytes + stats.space_freed_criteria_bytes + stats.space_saved_hardlinks_bytes) / (1024**3)
        logger.info(f"Space freed (dead trackers): {space_dead:.2f} GB")
        logger.info(f"Space freed (criteria):      {space_criteria:.2f} GB")
        logger.info(f"Space saved (hardlinks):     {space_hardlinks:.2f} GB")
        logger.info(f"Space saved (total):         {space_total:.2f} GB")

        if stats.deleted_torrents:
            logger.info(f"\nDeleted torrents:")
            for torrent_name in stats.deleted_torrents:
                logger.info(f"  - {torrent_name}")

        if file_cache:
            cache_stats = file_analyzer.get_cache_stats()
            logger.info(f"Cache hits: {cache_stats.hits}, misses: {cache_stats.misses}, "
                       f"hit rate: {cache_stats.hit_rate:.1%}")

        logger.info("=" * 80)

        discord_notifier.send_summary(stats, config.dry_run)

        if stats.hardlink_failures:
            failure_log = config.data_dir / 'logs' / 'hardlink-failures.log'
            with open(failure_log, 'a') as f:
                f.write(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                for failure in stats.hardlink_failures:
                    f.write(f"Torrent: {failure.torrent}\n")
                    f.write(f"  File: {failure.file}\n")
                    f.write(f"  Media: {failure.media_file}\n")
                    f.write(f"  Error: {failure.action.value} - {failure.message}\n")
            logger.warning(f"Hardlink failures written to {failure_log}")
            discord_notifier.send_hardlink_failures(stats.hardlink_failures)

        if file_cache:
            file_cache.close()

        logger.info("Torrent Cleaner finished successfully")
        lock_file.close()
        return 0

    except Exception as e:
        logger.exception(f"Fatal error: {e}")

        try:
            webhook_url = os.getenv('DISCORD_WEBHOOK_URL', '')
            if webhook_url:
                DiscordNotifier(webhook_url).send_error(f"Fatal error: {e}")
        except Exception as discord_error:
            logger.error(f"Failed to send Discord error notification: {discord_error}")

        if 'lock_file' in locals():
            lock_file.close()
        return 1


if __name__ == '__main__':
    sys.exit(main())
