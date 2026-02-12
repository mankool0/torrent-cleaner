"""File analysis for hardlink detection and hash comparison."""

import os
from pathlib import Path
from typing import List, Optional, Set
import logging

from src.utils.hash_utils import hash_file
from src.models import CacheStats, OrphanDetectionResult, OrphanDetectionStats, SizeIndex


class FileAnalyzer:
    """Analyze files for hardlink counts and hash matching."""

    # Media file extensions to prioritize
    MEDIA_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.wmv', '.flv', '.webm', '.ts', '.m2ts'}

    def __init__(self, cache=None):
        """Initialize file analyzer.

        Args:
            cache: Optional FileCache instance for caching file hashes.
        """
        self.logger = logging.getLogger(__name__)
        self.cache = cache
        self._cache_hits = 0
        self._cache_misses = 0
        self._size_index: SizeIndex = SizeIndex()

    def _hash_file_with_cache(self, file_path: str) -> str:
        """Hash a file, using cache if available.

        Args:
            file_path: Path to file

        Returns:
            Hash string
        """
        if self.cache:
            cached = self.cache.get_cached_hash(file_path)
            if cached is not None:
                self._cache_hits += 1
                return cached

            self._cache_misses += 1
            file_hash = hash_file(file_path)
            self.cache.store_hash(file_path, file_hash)
            return file_hash

        return hash_file(file_path)

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

    def build_size_index(self, media_dir: Path, extensions: Set[str] | None = None) -> SizeIndex:
        """
        Build size-based index of all files in media library.

        Args:
            media_dir: Root directory of media library
            extensions: Optional set of file extensions to index.
                       If None, indexes all files.

        Returns:
            SizeIndex mapping file sizes to lists of file paths
        """
        self.logger.info(f"Building media library size index for: {media_dir}")

        if not media_dir.exists():
            raise ValueError(f"Media directory does not exist: {media_dir}")

        size_index = SizeIndex()
        file_count = 0
        error_count = 0

        for file_path in media_dir.rglob('*'):
            if not file_path.is_file():
                continue

            if extensions and file_path.suffix.lower() not in extensions:
                continue

            try:
                size = os.stat(file_path).st_size
                size_index.add(size, str(file_path))
                file_count += 1

                if file_count % 1000 == 0:
                    self.logger.info(f"Indexed {file_count} files...")

            except (OSError, PermissionError) as e:
                self.logger.error(f"Error indexing file {file_path}: {e}")
                error_count += 1

        self.logger.info(f"Size index built: {file_count} files indexed, {error_count} errors")
        self._size_index = size_index
        return size_index

    def find_identical_file(
        self,
        orphaned_file: str,
        size_index: SizeIndex | None = None,
    ) -> Optional[str]:
        """
        Find identical file in media library using candidate-based matching.

        Finds candidates by file size, then hashes only those candidates
        to confirm a match.

        Args:
            orphaned_file: Path to orphaned file
            size_index: Optional SizeIndex (uses self._size_index if not provided)

        Returns:
            Path to identical file in media library, or None if not found
        """
        effective_size_index = size_index or self._size_index
        if not effective_size_index:
            self.logger.warning("No size index available for find_identical_file")
            return None

        try:
            orphaned_size = os.stat(orphaned_file).st_size
        except OSError as e:
            self.logger.error(f"Cannot stat orphaned file {orphaned_file}: {e}")
            return None

        candidates = effective_size_index.get_candidates(orphaned_size)
        if not candidates:
            return None

        try:
            orphaned_hash = self._hash_file_with_cache(str(orphaned_file))
        except Exception as e:
            self.logger.error(f"Error hashing orphaned file {orphaned_file}: {e}")
            return None

        for candidate in candidates:
            try:
                if not Path(candidate).exists():
                    continue
                candidate_hash = self._hash_file_with_cache(candidate)
                if candidate_hash == orphaned_hash:
                    self.logger.debug(f"Found identical file for {orphaned_file}: {candidate}")
                    return candidate
            except Exception as e:
                self.logger.error(f"Error hashing candidate {candidate}: {e}")
                continue

        return None

    def get_cache_stats(self) -> CacheStats:
        """Get cache hit/miss statistics."""
        total = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total if total > 0 else 0.0
        return CacheStats(
            hits=self._cache_hits,
            misses=self._cache_misses,
            hit_rate=hit_rate,
        )

    def is_media_file(self, file_path: str) -> bool:
        """
        Check if file is a media file based on extension.

        Args:
            file_path: Path to file

        Returns:
            True if file is a media file
        """
        return Path(file_path).suffix.lower() in self.MEDIA_EXTENSIONS
