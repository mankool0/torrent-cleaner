"""File analysis for hardlink detection and hash comparison."""

import os
from pathlib import Path
from typing import Dict, List, Set
import logging

from src.utils.hash_utils import hash_file
from src.models import MediaFileInfo, OrphanDetectionResult, OrphanDetectionStats


class FileAnalyzer:
    """Analyze files for hardlink counts and hash matching."""

    # Media file extensions to prioritize
    MEDIA_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.wmv', '.flv', '.webm', '.ts', '.m2ts'}

    def __init__(self):
        """Initialize file analyzer."""
        self.logger = logging.getLogger(__name__)
        self.media_index: Dict[str, MediaFileInfo] = {}

    def get_hardlink_count(self, file_path: str) -> int:
        """
        Get number of hardlinks for a file.

        Args:
            file_path: Path to file

        Returns:
            Number of hardlinks, or 0 if error
        """
        try:
            return os.stat(file_path).st_nlink
        except OSError as e:
            self.logger.error(f"Failed to get hardlink count for {file_path}: {e}")
            return 0

    def detect_orphaned_files(self, torrent_files: List[str]) -> OrphanDetectionResult:
        """
        Detect orphaned files (hardlink count = 1) in torrent file list.

        Args:
            torrent_files: List of absolute file paths

        Returns:
            OrphanDetectionResult with orphaned files, linked files, and stats
        """
        orphaned = []
        linked = []
        errors = []

        for file_path in torrent_files:
            try:
                path = Path(file_path)

                if not path.exists():
                    self.logger.warning(f"File does not exist: {file_path}")
                    errors.append(file_path)
                    continue

                if not path.is_file():
                    self.logger.debug(f"Skipping non-file: {file_path}")
                    continue

                link_count = self.get_hardlink_count(file_path)

                if link_count == 1:
                    orphaned.append(file_path)
                    self.logger.debug(f"Orphaned file (links={link_count}): {file_path}")
                else:
                    linked.append(file_path)
                    self.logger.debug(f"Linked file (links={link_count}): {file_path}")

            except (OSError, PermissionError) as e:
                self.logger.error(f"Error checking file {file_path}: {e}")
                errors.append(file_path)

        stats = OrphanDetectionStats(
            total=len(torrent_files),
            orphaned=len(orphaned),
            linked=len(linked),
            errors=len(errors)
        )

        self.logger.debug(f"File analysis: total={stats.total}, orphaned={stats.orphaned}, linked={stats.linked}, errors={stats.errors}")

        return OrphanDetectionResult(
            orphaned=orphaned,
            linked=linked,
            stats=stats
        )

    def build_media_library_index(self, media_dir: Path, extensions: Set[str] | None = None) -> Dict[str, MediaFileInfo]:
        """
        Build hash index of all files in media library.

        Args:
            media_dir: Root directory of media library
            extensions: Optional set of file extensions to index (e.g., {'.mkv', '.mp4'})
                       If None, indexes all files

        Returns:
            Dictionary mapping file hash to MediaFileInfo
        """
        self.logger.info(f"Building media library index for: {media_dir}")

        if not media_dir.exists():
            raise ValueError(f"Media directory does not exist: {media_dir}")

        index = {}
        file_count = 0
        error_count = 0

        for file_path in media_dir.rglob('*'):
            if not file_path.is_file():
                continue

            # Filter by extension if specified
            if extensions and file_path.suffix.lower() not in extensions:
                continue

            try:
                # Calculate hash
                file_hash = hash_file(file_path)
                stat_info = os.stat(file_path)

                # Store in index (last occurrence wins if hash collision)
                index[file_hash] = MediaFileInfo(
                    path=str(file_path),
                    size=stat_info.st_size,
                    inode=stat_info.st_ino
                )

                file_count += 1

                if file_count % 100 == 0:
                    self.logger.debug(f"Indexed {file_count} files...")

            except (OSError, PermissionError) as e:
                self.logger.error(f"Error indexing file {file_path}: {e}")
                error_count += 1

        self.logger.info(f"Media library index built: {file_count} files indexed, {error_count} errors")
        self.media_index = index
        return index

    def find_identical_file(self, orphaned_file: str, media_index: Dict[str, MediaFileInfo] | None = None) -> str | None:
        """
        Find identical file in media library by hash.

        Args:
            orphaned_file: Path to orphaned file
            media_index: Optional media index (uses self.media_index if not provided)

        Returns:
            Path to identical file in media library, or None if not found
        """
        if media_index is None:
            media_index = self.media_index

        try:
            # Calculate hash of orphaned file
            orphaned_hash = hash_file(orphaned_file)

            # Look up in media index
            if orphaned_hash in media_index:
                media_file_info = media_index[orphaned_hash]
                media_file_path = media_file_info.path

                # Verify file still exists and size matches
                media_path = Path(media_file_path)
                if not media_path.exists():
                    self.logger.warning(f"Media file no longer exists: {media_file_path}")
                    return None

                orphaned_size = os.stat(orphaned_file).st_size
                media_size = media_file_info.size

                if orphaned_size != media_size:
                    self.logger.warning(
                        f"Size mismatch for hash {orphaned_hash}: "
                        f"orphaned={orphaned_size}, media={media_size}"
                    )
                    return None

                self.logger.debug(f"Found identical file for {orphaned_file}: {media_file_path}")
                return media_file_path

            return None

        except Exception as e:
            self.logger.error(f"Error finding identical file for {orphaned_file}: {e}")
            return None

    def is_media_file(self, file_path: str) -> bool:
        """
        Check if file is a media file based on extension.

        Args:
            file_path: Path to file

        Returns:
            True if file is a media file
        """
        return Path(file_path).suffix.lower() in self.MEDIA_EXTENSIONS
