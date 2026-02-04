"""Atomic hardlink repair with rollback capability."""

import os
import shutil
from pathlib import Path
import logging
from typing import Dict, List

from src.models import HardlinkResult, HardlinkBatchResult, HardlinkFixResult, MediaFileInfo


class HardlinkFixer:
    """Fix broken hardlinks atomically with rollback support."""

    def __init__(self):
        """Initialize hardlink fixer."""
        self.logger = logging.getLogger(__name__)

    def fix_hardlink(self, orphaned_file: str, media_file: str, dry_run: bool = True) -> HardlinkResult:
        """
        Replace orphaned file with hardlink to media file.

        This operation is atomic:
        1. Rename orphaned file to .bak
        2. Create hardlink from media file
        3. On success: delete .bak
        4. On failure: restore .bak

        Args:
            orphaned_file: Path to orphaned file
            media_file: Path to media file to link to
            dry_run: If True, don't actually fix

        Returns:
            HardlinkResult with success flag, action type, and message
        """
        orphaned_path = Path(orphaned_file)
        media_path = Path(media_file)
        backup_path = orphaned_path.with_suffix(orphaned_path.suffix + '.bak')

        if not orphaned_path.exists():
            return HardlinkResult(
                success=False,
                action='validation_failed',
                message=f"Orphaned file does not exist: {orphaned_file}"
            )

        if not media_path.exists():
            return HardlinkResult(
                success=False,
                action='validation_failed',
                message=f"Media file does not exist: {media_file}"
            )

        if not orphaned_path.is_file() or not media_path.is_file():
            return HardlinkResult(
                success=False,
                action='validation_failed',
                message="Both paths must be regular files"
            )

        try:
            orphaned_size = os.stat(orphaned_path).st_size
            media_size = os.stat(media_path).st_size

            if orphaned_size != media_size:
                return HardlinkResult(
                    success=False,
                    action='size_mismatch',
                    message=f"Size mismatch: orphaned={orphaned_size}, media={media_size}"
                )
        except OSError as e:
            return HardlinkResult(
                success=False,
                action='stat_failed',
                message=f"Failed to stat files: {e}"
            )

        if dry_run:
            self.logger.info(f"[DRY RUN] Would fix hardlink: {orphaned_file} -> {media_file}")
            return HardlinkResult(
                success=True,
                action='dry_run',
                message=f"Would create hardlink from {media_file}"
            )

        try:
            # Step 1: Rename orphaned file to .bak
            self.logger.debug(f"Backing up: {orphaned_file} -> {backup_path}")
            orphaned_path.rename(backup_path)

            try:
                # Step 2: Create hardlink
                self.logger.debug(f"Creating hardlink: {media_file} -> {orphaned_file}")
                os.link(media_path, orphaned_path)

                # Step 3: Success - delete backup
                self.logger.debug(f"Deleting backup: {backup_path}")
                backup_path.unlink()

                self.logger.info(f"Successfully fixed hardlink: {orphaned_file} -> {media_file}")
                return HardlinkResult(
                    success=True,
                    action='fixed',
                    message=f"Created hardlink to {media_file}"
                )

            except OSError as e:
                # Step 4: Failure - restore backup
                self.logger.error(f"Failed to create hardlink: {e}")
                self.logger.info(f"Restoring backup: {backup_path} -> {orphaned_file}")

                try:
                    backup_path.rename(orphaned_path)
                    return HardlinkResult(
                        success=False,
                        action='link_failed_restored',
                        message=f"Failed to create hardlink (backup restored): {e}"
                    )
                except OSError as restore_error:
                    self.logger.critical(
                        f"CRITICAL: Failed to restore backup! "
                        f"Original: {orphaned_file}, Backup: {backup_path}, Error: {restore_error}"
                    )
                    return HardlinkResult(
                        success=False,
                        action='link_failed_restore_failed',
                        message=f"Failed to create hardlink AND restore backup: {e}, {restore_error}"
                    )

        except OSError as e:
            self.logger.error(f"Failed to backup file: {e}")
            return HardlinkResult(
                success=False,
                action='backup_failed',
                message=f"Failed to backup file: {e}"
            )

    def fix_orphaned_files(
        self,
        orphaned_files: List[str],
        media_index: Dict[str, MediaFileInfo],
        file_analyzer,
        dry_run: bool = True
    ) -> HardlinkBatchResult:
        """
        Fix multiple orphaned files by finding matches in media library.

        Args:
            orphaned_files: List of orphaned file paths
            media_index: Media library hash index
            file_analyzer: FileAnalyzer instance for finding identical files
            dry_run: If True, don't actually fix

        Returns:
            HardlinkBatchResult with counts and detailed results for each file
        """
        attempted = 0
        fixed = 0
        failed = 0
        media_files_fixed = 0
        results = []

        if not orphaned_files:
            return HardlinkBatchResult(
                attempted=0,
                fixed=0,
                failed=0,
                media_files_fixed=0,
                results=[]
            )

        self.logger.info(f"Attempting to fix {len(orphaned_files)} orphaned files...")

        for orphaned_file in orphaned_files:
            attempted += 1

            # Find identical file in media library
            media_file = file_analyzer.find_identical_file(orphaned_file, media_index)

            if media_file:
                self.logger.info(f"  Found match for: {Path(orphaned_file).name}")

                # Fix hardlink
                result = self.fix_hardlink(orphaned_file, media_file, dry_run=dry_run)

                if result.success:
                    fixed += 1

                    # Check if this is a media file
                    if file_analyzer.is_media_file(orphaned_file):
                        media_files_fixed += 1
                        self.logger.info(f"  Fixed media file hardlink: {Path(orphaned_file).name}")
                    else:
                        self.logger.info(f"  Fixed hardlink: {Path(orphaned_file).name}")
                else:
                    failed += 1
                    self.logger.warning(f"  Failed to fix hardlink: {result.message}")

                results.append(HardlinkFixResult(
                    file=orphaned_file,
                    media_file=media_file,
                    result=result
                ))
            else:
                self.logger.debug(f"  No match found for: {Path(orphaned_file).name}")

        return HardlinkBatchResult(
            attempted=attempted,
            fixed=fixed,
            failed=failed,
            media_files_fixed=media_files_fixed,
            results=results
        )
