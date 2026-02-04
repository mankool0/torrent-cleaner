"""Main entry point for torrent cleaner."""

import sys
import os
from pathlib import Path
import logging
from collections import defaultdict

from src.config import Config
from src.utils.logger import setup_logger
from src.qbittorrent_client import QBittorrentClient
from src.file_analyzer import FileAnalyzer
from src.hardlink_fixer import HardlinkFixer
from src.torrent_cleaner import TorrentCleaner
from src.discord_notifier import DiscordNotifier
from src.models import WorkflowStats


def run_workflow(config, qbt_client, file_analyzer, hardlink_fixer, torrent_cleaner, media_index):
    """
    Run the torrent cleaning workflow.

    Args:
        config: Config object
        qbt_client: QBittorrentClient instance
        file_analyzer: FileAnalyzer instance
        hardlink_fixer: HardlinkFixer instance
        torrent_cleaner: TorrentCleaner instance
        media_index: Dict mapping file hashes to MediaFileInfo

    Returns:
        WorkflowStats with workflow statistics
    """
    logger = logging.getLogger(__name__)
    stats = WorkflowStats()

    logger.info("Retrieving torrents from qBittorrent...")
    torrents = qbt_client.torrents_info()

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
    for torrent in torrents:
        stats.torrents_processed += 1

        torrent_name = torrent.name
        torrent_hash = torrent.hash
        save_path = Path(torrent.save_path)

        logger.info(f"\nProcessing torrent [{stats.torrents_processed}/{len(torrents)}]: {torrent_name}")

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

        if not deletion_check.should_delete:
            logger.info(f"  Keeping torrent (criteria not met)")
            stats.torrents_kept += 1
            stats.torrents_kept_criteria_not_met += 1
            continue

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

            # Check if files are already hardlinked to media library
            media_files_already_linked = 0
            if analysis.linked:
                # Files are hardlinked - verify they're linked to media library
                for linked_file in analysis.linked:
                    if not file_analyzer.is_media_file(linked_file):
                        continue
                    # Check if this file exists in media index
                    if file_analyzer.find_identical_file(linked_file, media_index):
                        media_files_already_linked += 1

            if media_files_already_linked > 0:
                logger.info(
                    f"  Keeping torrent ({media_files_already_linked} media file(s) already hardlinked)"
                )
                stats.torrents_kept += 1
                stats.torrents_kept_hardlinks_fixed += 1
                continue

            media_files_fixed = 0
            if config.fix_hardlinks and orphaned_files:
                # Pause torrent to prevent redownload during hardlink fix
                if not config.dry_run:
                    logger.info(f"  Pausing torrent '{torrent_name}' during hardlink fix")
                    qbt_client.torrents_pause(torrent_hashes=torrent_hash)

                fix_results = hardlink_fixer.fix_orphaned_files(
                    orphaned_files,
                    media_index,
                    file_analyzer,
                    dry_run=config.dry_run
                )

                stats.hardlinks_attempted += fix_results.attempted
                stats.hardlinks_fixed += fix_results.fixed
                stats.hardlinks_failed += fix_results.failed
                media_files_fixed = fix_results.media_files_fixed

                # Resume torrent after fixing
                if not config.dry_run:
                    logger.info(f"  Resuming torrent '{torrent_name}' after hardlink fix")
                    qbt_client.torrents_resume(torrent_hashes=torrent_hash)

            if media_files_fixed > 0:
                # Keep torrent if any media files were fixed
                logger.info(
                    f"  Keeping torrent (fixed {media_files_fixed} media file(s))"
                )
                stats.torrents_kept += 1
                stats.torrents_kept_hardlinks_fixed += 1
            else:
                logger.info(f"  Deleting torrent (meets criteria, no media files fixed)")

                success = torrent_cleaner.delete_torrent(
                    torrent_hash,
                    torrent_name,
                    delete_files=True
                )

                if success:
                    stats.torrents_deleted += 1
                    stats.deleted_torrents.append(torrent_name)

                    reason_key = f"age={deletion_check.stats.age}, ratio={deletion_check.stats.ratio:.2f}"
                    stats.deletion_reasons[reason_key] = stats.deletion_reasons.get(reason_key, 0) + 1

        except Exception as e:
            logger.error(f"  Error processing torrent files: {e}")
            continue

    return stats


def main():
    """Main workflow for torrent cleaning."""
    logger = None

    try:
        config = Config()

        logger = setup_logger('torrent-cleaner', config.log_level, config.log_file)
        logger.info("=" * 80)
        logger.info("Torrent Cleaner Starting")
        logger.info("=" * 80)
        logger.info(f"\n{config}")

        if config.dry_run:
            logger.warning("Running in DRY RUN mode - no changes will be made")

        logger.info("Initializing components...")
        qbt_client = QBittorrentClient(
            config.qbt_host,
            config.qbt_port,
            config.qbt_username,
            config.qbt_password
        )
        file_analyzer = FileAnalyzer()
        hardlink_fixer = HardlinkFixer()
        torrent_cleaner = TorrentCleaner(config, qbt_client)
        discord_notifier = DiscordNotifier(config.discord_webhook_url)

        logger.info("Building media library index...")
        media_index = file_analyzer.build_media_library_index(config.media_library_dir)

        stats = run_workflow(config, qbt_client, file_analyzer, hardlink_fixer, torrent_cleaner, media_index)

        qbt_client.close()

        logger.info("\n" + "=" * 80)
        logger.info("Torrent Cleaner Summary")
        logger.info("=" * 80)
        logger.info(f"Torrents processed: {stats.torrents_processed}")
        logger.info(f"Torrents deleted: {stats.torrents_deleted}")
        logger.info(f"Torrents kept: {stats.torrents_kept}")
        logger.info(f"  - Kept (criteria not met): {stats.torrents_kept_criteria_not_met}")
        logger.info(f"  - Kept (hardlinks fixed): {stats.torrents_kept_hardlinks_fixed}")
        logger.info(f"Hardlinks attempted: {stats.hardlinks_attempted}")
        logger.info(f"Hardlinks fixed: {stats.hardlinks_fixed}")
        logger.info(f"Hardlinks failed: {stats.hardlinks_failed}")
        logger.info(f"Orphaned files found: {stats.orphaned_files_found}")

        if stats.deleted_torrents:
            logger.info(f"\nDeleted torrents:")
            for torrent_name in stats.deleted_torrents:
                logger.info(f"  - {torrent_name}")

        logger.info("=" * 80)

        discord_notifier.send_summary(stats, config.dry_run)

        logger.info("Torrent Cleaner finished successfully")
        return 0

    except Exception as e:
        if logger:
            logger.exception(f"Fatal error: {e}")
        else:
            print(f"Fatal error: {e}", file=sys.stderr)

        try:
            config = Config()
            discord_notifier = DiscordNotifier(config.discord_webhook_url)
            discord_notifier.send_error(f"Fatal error: {e}")
        except Exception as discord_error:
            print(f"Failed to send Discord error notification: {discord_error}", file=sys.stderr)

        return 1


if __name__ == '__main__':
    sys.exit(main())
